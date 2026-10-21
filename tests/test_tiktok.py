import json
from pathlib import Path
from unittest.mock import Mock

from apify_client.errors import ApifyApiError

from veille.tools.tiktok import (
    OUTIL_CHERCHER_PUBS_TIKTOK,
    chercher_pubs_tiktok,
    est_du_domaine,
    normaliser_pub_tiktok,
)

DOSSIER_DONNEES = Path(__file__).parent / "donnees"


def charger(nom_fichier: str) -> list[dict]:
    return json.loads((DOSSIER_DONNEES / nom_fichier).read_text(encoding="utf-8"))


def faux_client_apify(brutes: list[dict], statut: str = "SUCCEEDED") -> Mock:
    client = Mock()
    client.actor.return_value.call.return_value = Mock(status=statut, default_dataset_id="dataset-test")
    client.dataset.return_value.list_items.return_value.items = brutes
    return client


def test_normaliser_vraies_pubs_tiktok():
    pubs = [normaliser_pub_tiktok(brute, "Typology") for brute in charger("tiktok_typology.json")]

    assert len(pubs) == 3
    for pub in pubs:
        assert pub.marque == "Typology"
        assert pub.annonceur == "GOOD BRANDS"
        assert "typology.com" in pub.lien
        assert pub.duree_jours >= 1
        assert pub.textes != []


def test_duree_jours():
    longue = normaliser_pub_tiktok({"adId": "1", "adStartDate": "2026-10-07", "adEndDate": "2026-10-20"}, "Typology")
    un_jour = normaliser_pub_tiktok({"adId": "2", "adStartDate": "2026-10-20", "adEndDate": "2026-10-20"}, "Typology")

    assert longue.duree_jours == 14  # du 7 au 20 inclus
    assert un_jour.duree_jours == 1


def test_pub_tiktok_incomplete():
    pub = normaliser_pub_tiktok({"adId": "123"}, "Typology")

    assert pub.duree_jours is None
    assert pub.textes == []
    assert pub.ciblage_age == []
    assert not pub.active


def test_pub_arretee():
    brute = charger("tiktok_respire.json")[0]  # status "unavailable"

    pub = normaliser_pub_tiktok(brute, "Respire")

    assert not pub.active


def test_aucune_donnee_personnelle():
    brute = {"adId": "1", "emails": ["contact@exemple.fr"], "phones": ["0600000000"]}

    donnees = normaliser_pub_tiktok(brute, "Typology").model_dump()

    assert "emails" not in donnees
    assert "phones" not in donnees


def test_est_du_domaine():
    assert est_du_domaine("https://www.typology.com/products/x", "typology.com")
    assert est_du_domaine("https://fr.typology.com/", "typology.com")
    assert not est_du_domaine("https://faketypology.com/", "typology.com")
    assert not est_du_domaine(None, "typology.com")


def test_chercher_pubs_tiktok_succes():
    client = faux_client_apify(charger("tiktok_typology.json"))

    resultat = chercher_pubs_tiktok("Typology", "typology.com", client)

    assert resultat["nb_pubs"] == 3
    assert "remarque" not in resultat


def test_chercher_pubs_tiktok_ecarte_le_bruit():
    # Les pubs « Respire » sont un film et une arnaque : aucune ne renvoie vers respire.co
    client = faux_client_apify(charger("tiktok_respire.json"))

    resultat = chercher_pubs_tiktok("Respire", "respire.co", client)

    assert resultat["nb_pubs"] == 0
    assert "remarque" in resultat
    assert "erreur" not in resultat


def test_chercher_pubs_tiktok_run_echoue():
    client = faux_client_apify([], statut="FAILED")

    resultat = chercher_pubs_tiktok("Typology", "typology.com", client)

    assert "erreur" in resultat
    client.dataset.assert_not_called()


def test_chercher_pubs_tiktok_apify_indisponible():
    client = faux_client_apify([])
    fausse_reponse = Mock(status_code=503, text="Service Unavailable")
    client.actor.return_value.call.side_effect = ApifyApiError(fausse_reponse, attempt=1)

    resultat = chercher_pubs_tiktok("Typology", "typology.com", client)

    assert "erreur" in resultat


def test_description_outil_tiktok():
    schema = OUTIL_CHERCHER_PUBS_TIKTOK["function"]["parameters"]

    assert sorted(schema["required"]) == ["domaine", "marque"]
    assert schema["properties"]["max_pubs"]["maximum"] == 3
    assert "client" not in schema["properties"]