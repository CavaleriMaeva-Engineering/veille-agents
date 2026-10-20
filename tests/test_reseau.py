from unittest.mock import Mock

import groq
import httpx
import pytest

from veille.reseau import (
    appeler_avec_tentatives,
    calculer_delai,
    code_est_passager,
    erreur_est_passagere,
)


def fausse_erreur(code: int) -> groq.APIStatusError:
    requete = httpx.Request("POST", "https://exemple.test")
    reponse = httpx.Response(code, request=requete)
    return groq.APIStatusError("erreur simulée", response=reponse, body=None)


def test_delai_double():
    assert calculer_delai(1, jitter=0) == 1
    assert calculer_delai(2, jitter=0) == 2
    assert calculer_delai(3, jitter=0) == 4


def test_delai_plafonne():
    assert calculer_delai(20, jitter=0) == 30
    assert 30 <= calculer_delai(7, plafond=30, jitter=1) <= 30 + 1

    assert calculer_delai(5, plafond=10, jitter=0) == 10


def test_code_est_passager():
    assert code_est_passager(429)
    assert code_est_passager(500)
    assert code_est_passager(503)

    assert not code_est_passager(400)
    assert not code_est_passager(401)
    assert not code_est_passager(404)


def test_succes_du_premier_coup():
    appel = Mock(return_value="réponse")
    attentes = []

    resultat = appeler_avec_tentatives(appel, attendre=attentes.append)

    assert resultat == "réponse"
    assert appel.call_count == 1
    assert attentes == []


def test_reessaie_erreur_passagere():
    appel = Mock(side_effect=[fausse_erreur(503), fausse_erreur(503), "réponse"])
    attentes = []

    resultat = appeler_avec_tentatives(appel, attendre=attentes.append)

    assert resultat == "réponse"
    assert appel.call_count == 3
    assert len(attentes) == 2


def test_abandonne_erreur_permanente():
    appel = Mock(side_effect=fausse_erreur(401))
    attentes = []

    with pytest.raises(groq.APIStatusError):
        appeler_avec_tentatives(appel, attendre=attentes.append)
    assert appel.call_count == 1
    assert attentes == []


def test_abandonne_apres_max_tentatives():
    appel = Mock(side_effect=fausse_erreur(503))
    attentes = []

    with pytest.raises(groq.APIStatusError):
        appeler_avec_tentatives(appel, max_tentatives=3, attendre=attentes.append)

    assert appel.call_count == 3
    assert len(attentes) == 2


def test_erreurs_httpx():
    assert erreur_est_passagere(httpx.ConnectTimeout("délai dépassé"))
    assert not erreur_est_passagere(httpx.UnsupportedProtocol("adresse invalide"))
