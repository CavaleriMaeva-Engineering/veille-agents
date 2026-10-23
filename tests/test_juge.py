from unittest.mock import Mock

import pytest
from test_rag import faux_encodeur, morceau

from veille.evals import juge as module_juge
from veille.evals.juge import (
    Jugement,
    Jugements,
    Paire,
    juger_deux_ordres,
    kappa_de_cohen,
    mesurer_accord,
)
from veille.evals.rag import CasRAG, pool_candidats
from veille.rag.recherche import MoteurRecherche

# --- Kappa de Cohen ---

def test_kappa_accord_parfait_et_hasard():
    assert kappa_de_cohen([True, False, True, False], [True, False, True, False]) == 1.0
    # 50 % d'accord avec des proportions 50/50 : exactement ce que donnerait le hasard
    assert kappa_de_cohen([True, True, False, False], [True, False, True, False]) == 0.0


def test_kappa_calcul_a_la_main():
    humain = [True] * 4 + [False] * 6
    juge = [True, True, True, False] + [True] + [False] * 5
    # p_o = 8/10 ; p_e = 0,4×0,4 + 0,6×0,6 = 0,52 ; κ = (0,8 − 0,52) / 0,48
    assert kappa_de_cohen(humain, juge) == pytest.approx(0.28 / 0.48)


# --- Biais de position : deux ordres ---

def test_deux_ordres_remet_les_verdicts_dans_l_ordre_d_origine(monkeypatch):
    reponses = [
        Jugements(jugements=[Jugement(numero=1, justification="", pertinent=True),
                             Jugement(numero=2, justification="", pertinent=False),
                             Jugement(numero=3, justification="", pertinent=False)]),
        # à l'envers, l'extrait d'origine n°3 est présenté en 1er… et le juge change d'avis sur lui
        Jugements(jugements=[Jugement(numero=1, justification="", pertinent=True),
                             Jugement(numero=2, justification="", pertinent=False),
                             Jugement(numero=3, justification="", pertinent=True)]),
    ]
    monkeypatch.setattr(module_juge, "generer_structure", lambda *a, **k: reponses.pop(0))

    verdicts = juger_deux_ordres(Mock(), "m", "q", ["a", "b", "c"], "t")

    assert verdicts == [(True, True), (False, False), (False, True)]


def test_extrait_oublie_par_le_juge(monkeypatch):
    monkeypatch.setattr(module_juge, "generer_structure", lambda *a, **k: Jugements(
        jugements=[Jugement(numero=1, justification="", pertinent=True)]))
    assert juger_deux_ordres(Mock(), "m", "q", ["a", "b"], "t") == [(True, None), (None, True)]


# --- Mesure de l'accord ---

def paire(humain, endroit, envers=None, longueur=100):
    return Paire(cas="c", morceau="m", longueur=longueur, humain=humain, endroit=endroit,
                 envers=endroit if envers is None else envers)


def test_accord_faux_positifs_et_instables():
    paires = [paire(True, True), paire(True, False), paire(False, True), paire(False, False),
              paire(False, False), paire(True, True, envers=False)]          # la dernière change avec l'ordre
    accord = mesurer_accord(paires)
    assert accord.nb_coherentes == 5 and accord.taux_changement_position == pytest.approx(1 / 6, abs=1e-3)
    assert accord.accord == 0.6 and accord.faux_positifs == 1 and accord.faux_negatifs == 1
    assert accord.precision_juge == 0.5 and accord.rappel_juge == 0.5


def test_biais_de_longueur_visible():
    # l'humaine juge pareil quelle que soit la longueur ; le juge dit « pertinent » à tous les extraits longs
    paires = [paire(False, False, longueur=50), paire(True, True, longueur=60),
              paire(False, True, longueur=500), paire(True, True, longueur=600)]
    accord = mesurer_accord(paires)
    assert accord.pertinents_longs_humain == 0.5 and accord.pertinents_longs_juge == 1.0


# --- Même pooling pour l'humaine et le juge ---

def test_pool_sans_doublon_et_filtre_de_marque():
    moteur = MoteurRecherche([morceau("a", "coffret Noël"), morceau("b", "coffret cadeau"),
                              morceau("c", "coffret", marque="Respire")], faux_encodeur)
    moteur.reranker = lambda q, textes: [0.0] * len(textes)
    candidats = pool_candidats(moteur, CasRAG(id="x", question="coffret", type="normal", marque="Typology"))
    assert sorted(m.id for m in candidats) == ["a", "b"]
