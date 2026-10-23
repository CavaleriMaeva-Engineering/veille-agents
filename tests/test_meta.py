import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from apify_client.errors import ApifyApiError

from veille.tools.meta import (
    OUTIL_CHERCHER_PUBS_META,
    chercher_pubs_meta,
    est_un_vrai_texte,
    normaliser_pub_meta,
)

DOSSIER_DONNEES = Path(__file__).parent / "donnees"


def charger_pubs_typology() -> list[dict]:
    fichier = DOSSIER_DONNEES / "meta_typology.json"
    return json.loads(fichier.read_text(encoding="utf-8"))


def faux_client_apify(brutes: list[dict], statut: str = "SUCCEEDED") -> Mock:
    client = Mock()
    client.actor.return_value.call.return_value = Mock(status=statut, default_dataset_id="dataset-test")
    client.dataset.return_value.list_items.return_value.items = brutes
    return client


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


def test_chercher_pubs_meta_succes():
    client = faux_client_apify(charger_pubs_typology())

    resultat = chercher_pubs_meta("Typology", client)

    assert resultat["nb_pubs"] == 5
    assert "erreur" not in resultat
    assert "remarque" not in resultat
    assert resultat["pubs"][0]["marque"] == "Typology"


def test_chercher_pubs_meta_filtre_les_autres_pages():
    pub_revendeur = {"pageName": "Revendeur Beauté", "adArchiveID": "999"} # Fausse pub
    brutes = charger_pubs_typology() + [pub_revendeur] # Vraies pubs Typology + fausse pub
    client = faux_client_apify(brutes)

    resultat = chercher_pubs_meta("Typology", client)

    assert resultat["nb_pubs"] == 5 # On vérifie qu'on a bien toujours 5 pubs et pas 6 (que la fausse pub n'est pas prise en compte)


def test_chercher_pubs_meta_aucune_pub_de_la_marque():
    client = faux_client_apify(charger_pubs_typology())

    resultat = chercher_pubs_meta("Respire", client)

    assert resultat["nb_pubs"] == 0
    assert "remarque" in resultat
    assert "erreur" not in resultat


def test_chercher_pubs_meta_run_echoue():
    client = faux_client_apify([], statut="FAILED")

    resultat = chercher_pubs_meta("Typology", client)

    assert "erreur" in resultat
    client.dataset.assert_not_called()


def test_chercher_pubs_meta_run_none():
    client = faux_client_apify([])
    client.actor.return_value.call.return_value = None

    resultat = chercher_pubs_meta("Typology", client)

    assert "erreur" in resultat


def test_chercher_pubs_meta_apify_indisponible():
    client = faux_client_apify([])
    fausse_reponse = Mock(status_code=503, text="Service Unavailable")
    client.actor.return_value.call.side_effect = ApifyApiError(fausse_reponse, attempt=1)

    resultat = chercher_pubs_meta("Typology", client)

    assert "erreur" in resultat


def test_description_outil_meta():
       schema = OUTIL_CHERCHER_PUBS_META["function"]["parameters"]

       assert OUTIL_CHERCHER_PUBS_META["function"]["name"] == "chercher_pubs_meta"
       assert schema["required"] == ["marque"]
       assert schema["properties"]["max_pubs"]["maximum"] == 20
       assert "client" not in schema["properties"]



def test_duree_jours_meta():
    brute = {"adArchiveID": "1", "pageName": "Typology", "startDateFormatted": "2026-01-14T08:00:00Z"}

    pub = normaliser_pub_meta(brute, aujourd_hui=date(2026, 10, 22))

    assert pub.duree_jours == 282   # du 14 janvier au 22 octobre inclus


def test_duree_jours_meta_sans_date():
    pub = normaliser_pub_meta({"adArchiveID": "1", "pageName": "Typology"}, aujourd_hui=date(2026, 10, 22))

    assert pub.duree_jours is None


def test_chercher_pubs_meta_garde_par_domaine():
    pub_autre_page = {"adArchiveID": "9", "pageName": "Typology Paris Officiel", "isActive": True,
                      "snapshot": {"linkUrl": "https://www.typology.com/produit"}}
    client = faux_client_apify([pub_autre_page])

    resultat = chercher_pubs_meta("Typology", client, domaine="typology.com")

    assert resultat["nb_pubs"] == 1   # nom de page différent, mais le lien mène au site de la marque


def test_chercher_pubs_meta_cherche_plus_large_que_ce_qu_il_garde():
    client = faux_client_apify(charger_pubs_typology())

    resultat = chercher_pubs_meta("Typology", client, max_pubs=2)

    assert resultat["nb_pubs"] == 2
    assert client.actor.return_value.call.call_args.kwargs["run_input"]["resultsLimit"] == 6