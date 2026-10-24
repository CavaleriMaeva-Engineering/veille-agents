import json
import threading
from types import SimpleNamespace

import pytest

from veille.api.executions import (
    DejaEnCours,
    Execution,
    Options,
    Registre,
    evenement_depuis_span,
    formater_sse,
    nom_d_erreur,
    resumer,
)
from veille.traces import lire_spans, span


def un_span(type_, nom="x", statut="ok", erreur=None, **attributs):
    donnees = {"type": type_, "nom": nom, "statut": statut, "duree_ms": 12.5, "attributs": attributs}
    if erreur:
        donnees["erreur"] = erreur
    return donnees


# --- Ce qui sort de l'API ---------------------------------------------------------------------------

def test_un_span_llm_expose_les_tokens_et_pas_le_reste():
    evenement = evenement_depuis_span(un_span(
        "llm", agent="collecteur", modele="m", tentative=1, tokens_entree=100, tokens_caches=0, tokens_sortie=20,
        cout_usd=0.0001, execution_id="veille-1", prompt_secret="ne pas sortir",
    ))
    assert evenement["tokens_entree"] == 100
    assert evenement["agent"] == "collecteur"
    assert "prompt_secret" not in evenement and "execution_id" not in evenement


def test_une_erreur_ne_sort_que_par_son_nom():
    brute = "RateLimitError(\"Error code: 429 - organization `org_01abc` service tier on_demand\")"

    evenement = evenement_depuis_span(un_span("llm", statut="erreur", erreur=brute, agent="a"))

    assert evenement["erreur"] == "RateLimitError"
    assert "org_01abc" not in json.dumps(evenement)


def test_les_arguments_d_un_outil_ne_sortent_pas():
    evenement = evenement_depuis_span(un_span(
        "outil", "lire_page_web", arguments='{"url": "https://x.fr/?token=abc"}', resultat="ok", caracteres=120,
    ))
    assert evenement == {
        "type": "outil", "nom": "lire_page_web", "statut": "ok", "duree_ms": 12.5, "resultat": "ok", "caracteres": 120,
    }


def test_le_span_racine_n_est_pas_un_evenement():
    assert evenement_depuis_span(un_span("execution", "veille-1")) is None


def test_nom_d_erreur():
    assert nom_d_erreur("ValueError('x')") == "ValueError"
    assert nom_d_erreur("KeyboardInterrupt") == "KeyboardInterrupt"
    assert nom_d_erreur("") == "Erreur"


def test_format_sse():
    texte = formater_sse({"id": 3, "type": "span", "donnees": {"nom": "été\nligne"}})
    assert texte == 'id: 3\nevent: span\ndata: {"nom": "été\\nligne"}\n\n'   # le retour à la ligne est échappé


def test_resume_d_un_resultat():
    analyse = SimpleNamespace(
        marque="Typology", decision="redige", nb_collectes=2, signaux=SimpleNamespace(nb_pubs={"meta": 4, "tiktok": 1}),
        changements=SimpleNamespace(comparable=True, score=0.4), alertes=["a"],
    )
    resultat = SimpleNamespace(analyses=[analyse], echecs={"Horace": "BadRequestError('Error code: 400 ...')"})

    assert resumer(resultat) == {
        "marques": [{"marque": "Typology", "decision": "redige", "nb_collectes": 2, "nb_pubs": 5,
                     "score_changement": 0.4, "nb_alertes": 1}],
        "echecs": {"Horace": "BadRequestError"},
    }


# --- Le flux d'événements --------------------------------------------------------------------------

def execution_avec(*types):
    execution = Execution("veille-aaaaaaaa", Options())
    for i, type_ in enumerate(types):
        execution.ajouter(type_, {"n": i})
    return execution


def test_le_flux_remet_tout_dans_l_ordre_puis_s_arrete():
    execution = execution_avec("span", "span")
    execution.terminer("terminee", resume={"marques": []})

    evenements = list(execution.suivre(delai_ping=0.01))

    assert [(e["id"], e["type"]) for e in evenements] == [(1, "span"), (2, "span"), (3, "fin")]
    assert evenements[-1]["donnees"]["statut"] == "terminee"


def test_reprise_apres_une_coupure():
    execution = execution_avec("span", "span", "span")
    execution.terminer("terminee")

    evenements = list(execution.suivre(apres=2, delai_ping=0.01))

    assert [e["id"] for e in evenements] == [3, 4]   # Last-Event-ID: 2 -> on reprend à 3


def test_ping_quand_rien_ne_se_passe():
    execution = Execution("veille-aaaaaaaa", Options())
    flux = execution.suivre(delai_ping=0.01)

    assert next(flux) is None   # ni événement ni fin : le serveur enverra un commentaire de garde


def test_un_lecteur_connecte_pendant_le_run_recoit_les_evenements_en_direct():
    execution = Execution("veille-aaaaaaaa", Options())
    recus = []
    lecteur = threading.Thread(target=lambda: recus.extend(e for e in execution.suivre(delai_ping=0.05) if e))
    lecteur.start()

    execution.ajouter("span", {"n": 1})
    execution.terminer("terminee")
    lecteur.join(timeout=5)

    assert not lecteur.is_alive()
    assert [e["type"] for e in recus] == ["span", "fin"]


# --- Le registre : un seul run à la fois ---------------------------------------------------------------

def resultat_vide():
    return SimpleNamespace(analyses=[], echecs={})


def test_deux_veilles_en_meme_temps_sont_refusees(tmp_path):
    libere = threading.Event()

    def lanceur(config, memoire, execution_id):
        libere.wait(timeout=5)
        return resultat_vide()

    registre = Registre(lanceur, tmp_path)
    premiere = registre.demarrer(None, Options())

    with pytest.raises(DejaEnCours) as refus:
        registre.demarrer(None, Options())
    assert refus.value.execution_id == premiere.id

    libere.set()
    assert premiere.attendre(timeout=5)
    assert registre.demarrer(None, Options()).id != premiere.id   # le verrou est libéré avant « fin »


def test_les_spans_du_run_deviennent_des_evenements_et_une_trace(tmp_path):
    def lanceur(config, memoire, execution_id):
        with span("etape", "collecte", marque="Typology"), span("outil", "lire_page_web") as attributs:
            attributs.update(resultat="ok", caracteres=10)
        return resultat_vide()

    execution = Registre(lanceur, tmp_path).demarrer(None, Options())
    assert execution.attendre(timeout=5)

    evenements = list(execution.suivre(delai_ping=0.01))
    assert [e["donnees"].get("nom") for e in evenements if e["type"] == "span"] == ["lire_page_web", "collecte"]
    assert evenements[-1]["donnees"]["statut"] == "terminee"
    spans = lire_spans(tmp_path / f"{execution.id}.jsonl")
    assert {s["type"] for s in spans} == {"execution", "etape", "outil"}


def test_un_echec_est_annonce_sans_le_message_brut(tmp_path):
    def lanceur(config, memoire, execution_id):
        raise RuntimeError("clé secrète sk-123 dans le message")

    execution = Registre(lanceur, tmp_path).demarrer(None, Options())
    assert execution.attendre(timeout=5)

    assert execution.statut == "echec"
    assert execution.erreur == "RuntimeError"
    assert "sk-123" not in json.dumps(execution.vue())
    fin = list(execution.suivre(delai_ping=0.01))[-1]
    assert fin["type"] == "fin" and fin["donnees"]["erreur"] == "RuntimeError"


def test_les_options_sont_transmises_au_lanceur(tmp_path):
    recu = {}

    def lanceur(config, memoire, execution_id):
        recu.update(config=config, memoire=memoire, id=execution_id)
        return resultat_vide()

    execution = Registre(lanceur, tmp_path).demarrer("la-config", Options(memoire=True))
    assert execution.attendre(timeout=5)

    assert recu == {"config": "la-config", "memoire": True, "id": execution.id}


def test_le_registre_n_garde_que_les_plus_recentes(tmp_path, monkeypatch):
    monkeypatch.setattr("veille.api.executions.MAX_EXECUTIONS_EN_MEMOIRE", 2)
    registre = Registre(lambda config, memoire, execution_id: resultat_vide(), tmp_path)

    ids = []
    for _ in range(3):
        execution = registre.demarrer(None, Options())
        assert execution.attendre(timeout=5)
        ids.append(execution.id)

    assert registre.trouver(ids[0]) is None
    assert [e.id for e in registre.recentes()] == [ids[2], ids[1]]
