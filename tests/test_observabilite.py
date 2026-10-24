import asyncio
import json
from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import BaseModel

from veille.couts import cout_anthropic, cout_groq, faire_bilan, formater_bilan
from veille.llm.client import AppelOutil, appeler_llm
from veille.parallele import executer_en_parallele
from veille.settings import Config, Marque, ReglageLLM
from veille.tools.registre import Outil, executer_appel_outil
from veille.traces import lire_spans, noter, span, tracer

VINGT = "openai/gpt-oss-20b"


def reponse_groq(entree=1000, sortie=200, caches=None, raisonnement=None):
    usage = SimpleNamespace(prompt_tokens=entree, completion_tokens=sortie)
    if caches is not None:
        usage.prompt_tokens_details = SimpleNamespace(cached_tokens=caches)
    if raisonnement is not None:
        usage.completion_tokens_details = SimpleNamespace(reasoning_tokens=raisonnement)
    message = SimpleNamespace(content="ok", tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


# --- Spans ---------------------------------------------------------------------------------------

def test_spans_imbriques_ecrits_en_jsonl(tmp_path):
    with tracer("run-1", tmp_path) as trace, span("etape", "collecte", marque="Typology") as attributs:
        with span("outil", "lire_page_web"):
            pass
        attributs["nb"] = 3

    spans = {s["nom"]: s for s in lire_spans(trace.chemin)}
    assert set(spans) == {"run-1", "collecte", "lire_page_web"}
    assert spans["lire_page_web"]["parent_id"] == spans["collecte"]["span_id"]
    assert spans["collecte"]["parent_id"] == spans["run-1"]["span_id"]
    assert spans["collecte"]["attributs"] == {"marque": "Typology", "nb": 3}   # complété par le bloc
    assert all(s["trace_id"] == "run-1" and s["statut"] == "ok" for s in spans.values())


def test_un_span_note_l_erreur_et_la_laisse_remonter(tmp_path):
    with tracer("run-2", tmp_path) as trace, pytest.raises(ValueError), span("outil", "chercher_pubs_meta"):
        raise ValueError("panne")

    outil = next(s for s in lire_spans(trace.chemin) if s["type"] == "outil")
    assert outil["statut"] == "erreur"
    assert "panne" in outil["erreur"]


def test_sans_trace_active_rien_n_est_ecrit(tmp_path):
    with span("llm", "m") as attributs:
        noter(cout=1)
    assert attributs == {"cout": 1}
    assert list(tmp_path.iterdir()) == []


def test_le_parent_suit_les_outils_lances_en_parallele(tmp_path):
    def travail(i):
        with span("outil", f"outil-{i}"):
            return i

    with tracer("run-3", tmp_path) as trace, span("etape", "tour") as _:
        asyncio.run(executer_en_parallele([partial(travail, i) for i in range(3)]))

    spans = lire_spans(trace.chemin)
    tour = next(s for s in spans if s["nom"] == "tour")
    outils = [s for s in spans if s["type"] == "outil"]
    assert len(outils) == 3
    assert all(s["parent_id"] == tour["span_id"] for s in outils)   # contexte copié dans les threads


# --- Appels LLM et outils instrumentés ----------------------------------------------------------

def test_appel_llm_trace_tokens_caches_et_raisonnement(tmp_path):
    client = Mock()
    client.chat.completions.create.return_value = reponse_groq(1000, 200, caches=600, raisonnement=150)

    with tracer("run-4", tmp_path) as trace:
        reponse = appeler_llm(client, VINGT, [], agent="redacteur", execution_id="e", effort_raisonnement="low")

    assert (reponse.tokens_caches, reponse.tokens_raisonnement) == (600, 150)
    llm = next(s for s in lire_spans(trace.chemin) if s["type"] == "llm")
    assert llm["attributs"]["agent"] == "redacteur"
    assert llm["attributs"]["effort"] == "low"
    assert llm["attributs"]["cout_usd"] == pytest.approx(cout_groq(VINGT, 1000, 600, 200))


def test_usage_sans_details_compte_zero_token_en_cache():
    client = Mock()
    client.chat.completions.create.return_value = reponse_groq()

    reponse = appeler_llm(client, VINGT, [], agent="a", execution_id="e")

    assert (reponse.tokens_caches, reponse.tokens_raisonnement) == (0, 0)


class Args(BaseModel):
    url: str


def test_appel_d_outil_trace_issue_et_taille(tmp_path):
    outils = {"lire_page_web": Outil({"function": {"name": "lire_page_web"}}, Args, lambda url: {"texte": "abc"})}

    with tracer("run-5", tmp_path) as trace:
        executer_appel_outil(AppelOutil(id="1", nom="lire_page_web", arguments='{"url": "https://x.fr"}'), outils)
        executer_appel_outil(AppelOutil(id="2", nom="inconnu", arguments="{}"), outils)
        executer_appel_outil(AppelOutil(id="3", nom="lire_page_web", arguments="{}"), outils)

    resultats = [s["attributs"]["resultat"] for s in lire_spans(trace.chemin) if s["type"] == "outil"]
    assert resultats == ["ok", "outil_inconnu", "arguments_invalides"]
    ok = next(s for s in lire_spans(trace.chemin) if s["attributs"].get("resultat") == "ok")
    assert ok["attributs"]["caracteres"] == len(json.dumps({"texte": "abc"}))


# --- Coûts --------------------------------------------------------------------------------------

def test_cout_groq_cache_a_moitie_prix():
    plein = cout_groq(VINGT, 1_000_000, 0, 0)
    assert plein == pytest.approx(0.075)
    assert cout_groq(VINGT, 1_000_000, 1_000_000, 0) == pytest.approx(plein / 2)
    assert cout_groq("modele-inconnu", 10, 0, 10) is None


def test_cout_anthropic_equivalent_avec_et_sans_cache():
    # Haiku 5.5 : 0,10 $ en entrée, 0,01 $ en lecture de cache, 0,125 $ en écriture, 0,50 $ en sortie
    assert cout_anthropic(VINGT, 1_000_000, 0, 1_000_000, avec_cache=False) == pytest.approx(0.60)
    assert cout_anthropic(VINGT, 1_000_000, 800_000, 0, avec_cache=True) == pytest.approx(0.2 * 0.125 + 0.8 * 0.01)


def test_bilan_par_agent_et_par_outil(tmp_path):
    client = Mock()
    client.chat.completions.create.side_effect = [reponse_groq(1000, 100, caches=0), reponse_groq(2000, 100, caches=1000)]

    with tracer("run-6", tmp_path) as trace:
        appeler_llm(client, VINGT, [], agent="collecteur", execution_id="e")
        appeler_llm(client, VINGT, [], agent="redacteur", execution_id="e")
        with span("outil", "chercher_pubs_meta") as attributs:
            attributs.update(resultat="erreur", caracteres=40, cout_apify_usd=0.01)

    bilan = faire_bilan(lire_spans(trace.chemin))
    assert bilan.execution_id == "run-6"
    assert bilan.total.appels == 2
    assert bilan.total.tokens_entree == 3000
    assert bilan.total.taux_cache == pytest.approx(1 / 3)
    assert bilan.total.cout_groq == pytest.approx(cout_groq(VINGT, 1000, 0, 100) + cout_groq(VINGT, 2000, 1000, 100))
    assert {ligne.cle for ligne in bilan.par_agent} == {"collecteur", "redacteur"}
    assert bilan.par_outil[0].erreurs == 1
    assert bilan.cout_apify == pytest.approx(0.01)
    assert "| **total** | 2 |" in formater_bilan(bilan)


def test_une_tentative_en_echec_est_comptee_sans_tokens(tmp_path):
    client = Mock()
    client.chat.completions.create.side_effect = ValueError("400")

    with tracer("run-7", tmp_path) as trace, pytest.raises(ValueError):
        appeler_llm(client, VINGT, [], agent="redacteur", execution_id="e")

    bilan = faire_bilan(lire_spans(trace.chemin))
    assert (bilan.total.appels, bilan.total.echecs, bilan.total.tokens_entree) == (0, 1, 0)


# --- Routage par étape --------------------------------------------------------------------------

def test_reglage_par_etape_et_valeurs_par_defaut():
    config = Config(
        marche="t", modele=VINGT, marques=[Marque(nom="T", site="https://t.fr")],
        etapes={"collecteur": ReglageLLM(effort="low"), "synthese": ReglageLLM(modele="openai/gpt-oss-120b")},
    )
    assert config.reglage("collecteur") == (VINGT, "low")
    assert config.reglage("synthese") == ("openai/gpt-oss-120b", None)
    assert config.reglage("redacteur") == (VINGT, None)
