import json
from pathlib import Path

from veille.tools.tiktok import normaliser_pub_tiktok

DOSSIER_DONNEES = Path(__file__).parent / "donnees"


def charger(nom_fichier: str) -> list[dict]:
    return json.loads((DOSSIER_DONNEES / nom_fichier).read_text(encoding="utf-8"))


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

    assert longue.duree_jours == 13 + 1      # du 7 au 20 inclus
    assert un_jour.duree_jours == 1


def test_pub_tiktok_incomplete():
    pub = normaliser_pub_tiktok({"adId": "123"}, "Typology")

    assert pub.duree_jours is None
    assert pub.textes == []
    assert pub.ciblage_age == []
    assert not pub.active


def test_pub_arretee():
    brute = charger("tiktok_respire.json")[0]      # status "unavailable"

    pub = normaliser_pub_tiktok(brute, "Respire")

    assert not pub.active


def test_aucune_donnee_personnelle():
    brute = {"adId": "1", "emails": ["contact@exemple.fr"], "phones": ["0600000000"]}

    donnees = normaliser_pub_tiktok(brute, "Typology").model_dump()

    assert "emails" not in donnees
    assert "phones" not in donnees