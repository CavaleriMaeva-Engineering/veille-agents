import json
from pathlib import Path

from veille.tools.meta import est_un_vrai_texte, normaliser_pub_meta

DOSSIER_DONNEES = Path(__file__).parent / "donnees"


def charger_pubs_typology() -> list[dict]:
    fichier = DOSSIER_DONNEES / "meta_typology.json"
    return json.loads(fichier.read_text(encoding="utf-8"))


def test_normaliser_vraies_pubs():
    pubs = [normaliser_pub_meta(brute) for brute in charger_pubs_typology()]

    assert len(pubs) == 5
    for pub in pubs:
        assert pub.marque == "Typology"
        assert pub.id != ""
        for texte in pub.textes:
            assert "{{" not in texte


def test_est_un_vrai_texte():
    assert not est_un_vrai_texte(None)
    assert not est_un_vrai_texte("")
    assert not est_un_vrai_texte("    ")
    assert not est_un_vrai_texte("{{product.brand}}")
    assert est_un_vrai_texte("98% d'origine naturelle.")


def test_pub_incomplete():
    brute = {"adArchiveID": "123", "pageName": "Respire", "isActive": True}

    pub = normaliser_pub_meta(brute)

    assert pub.textes == []
    assert pub.lien is None
    assert pub.plateformes == []
