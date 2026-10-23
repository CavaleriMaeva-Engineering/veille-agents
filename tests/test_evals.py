from unittest.mock import Mock

import pytest
from test_rag import faux_encodeur, morceau
from test_superviseur import analyse_d_hier, collecte, config_de_test, signaux

from veille.agents.analyste import Trajectoire
from veille.agents.rapport import Constat
from veille.agents.superviseur import lancer_veille
from veille.evals.metriques import precision_a_k, rang_reciproque, rappel_a_k
from veille.evals.production import evaluer_redactions, evaluer_trajectoires, tableau
from veille.evals.rag import (
    Annotation,
    CasRAG,
    charger_annotations,
    charger_cas,
    enregistrer_annotations,
    evaluer_recherche,
)
from veille.rag.recherche import MoteurRecherche

# --- Métriques ---

def test_precision_rappel_et_rang_reciproque():
    trouves, pertinents = ["a", "x", "b", "y", "z"], {"a", "b", "c"}
    assert precision_a_k(trouves, pertinents, 5) == pytest.approx(2 / 5)
    assert rappel_a_k(trouves, pertinents, 5) == pytest.approx(2 / 3)
    assert rang_reciproque(["x", "b"], pertinents) == 0.5
    assert rang_reciproque(["x", "y"], pertinents) == 0.0


# --- Cas et annotations ---

def test_les_cas_du_projet_sont_valides():
    cas = charger_cas()
    assert len(cas) >= 20 and len({c.id for c in cas}) == len(cas)
    assert {c.type for c in cas} == {"normal", "limite", "adverse"}
    assert all(c.attendu == "abstention" for c in cas if c.type == "adverse")


def test_annotations_aller_retour(tmp_path):
    chemin = tmp_path / "annotations.json"
    enregistrer_annotations({"r01": Annotation(pertinents=["a"], annote_par="maeva", annote_le="2026-10-24")}, chemin)
    assert charger_annotations(chemin)["r01"].pertinents == ["a"]
    assert charger_annotations(tmp_path / "absent.json") == {}


# --- Recherche ---

def test_evaluer_recherche_compare_les_modes_et_ignore_les_cas_sans_pertinent():
    moteur = MoteurRecherche([morceau("coffret", "coffret de Noël offert"), morceau("serum", "sérum vitamine")],
                             faux_encodeur)
    cas = [CasRAG(id="c1", question="coffret Noël", type="normal"),
           CasRAG(id="c2", question="Nivea", type="adverse", attendu="abstention")]
    annotations = {"c1": Annotation(pertinents=["coffret"], annote_par="m", annote_le="d"),
                   "c2": Annotation(pertinents=[], annote_par="m", annote_le="d")}

    scores, details = evaluer_recherche(moteur, cas, annotations, ["bm25", "hybride"], k=1)

    assert [s.mode for s in scores] == ["bm25", "hybride"]
    assert all(s.nb_cas == 1 and s.mrr == 1.0 and s.premier_pertinent == 1.0 for s in scores)
    assert {d["cas"] for d in details} == {"c1"}


# --- Rédacteur et agent, sur des analyses enregistrées ---

def test_taux_d_ancrage_des_constats():
    analyse = analyse_d_hier(signaux()).model_copy(update={"observations": ['{"texte": "offert dès 75 €"}']})
    rapport = analyse.rapport.model_copy(update={"offres": [
        Constat(affirmation="Offert dès 75 €.", sources=["meta"]),
        Constat(affirmation="Remise de 40 %.", sources=["meta"]),
    ]})
    score = evaluer_redactions([analyse.model_copy(update={"rapport": rapport})])
    assert score.nb_constats == 2 and score.taux_ancrage == 0.5


def test_trajectoire_enregistree_puis_evaluee():
    trajectoire = Trajectoire(tours=2, arret="reponse_finale", tokens=1800, appels=["chercher_pubs_meta"])
    avec_trajectoire = collecte().model_copy(update={"trajectoire": trajectoire})
    resultat = lancer_veille(
        config_de_test(), Mock(), Mock(), "essai", collecter=Mock(return_value=avec_trajectoire),
        rediger=Mock(return_value=analyse_d_hier(signaux()).rapport), enregistrer=Mock(),
        charger_precedente=lambda nom: None,
    )
    reussie = resultat.analyses[0]
    ratee = reussie.model_copy(update={
        "trajectoire": trajectoire.model_copy(update={"arret": "limite_tours", "tours": 5}), "nb_collectes": 2,
    })

    score = evaluer_trajectoires([reussie, ratee, analyse_d_hier(signaux())])   # la 3e n'a pas de trajectoire

    assert reussie.trajectoire == trajectoire
    assert score.nb_collectes == 2 and score.taux_succes == 0.5
    assert score.tours_moyens == 3.5 and score.taux_limite_tours == 0.5 and score.taux_relance == 0.5


def test_tableau_markdown():
    texte = tableau([CasRAG(id="c1", question="q", type="normal")])
    assert texte.splitlines()[0].startswith("| id | question | type |") and "| c1 | q | normal |" in texte
