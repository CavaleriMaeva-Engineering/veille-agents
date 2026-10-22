import json
from unittest.mock import Mock

from veille.llm.client import AppelOutil
from veille.tools.meta import OUTIL_CHERCHER_PUBS_META, ArgsChercherPubsMeta
from veille.tools.registre import Outil, creer_outils, executer_appel_outil


def outils_de_test(fonction: Mock) -> dict[str, Outil]:
    return {"chercher_pubs_meta": Outil(OUTIL_CHERCHER_PUBS_META, ArgsChercherPubsMeta, fonction)}


def test_appel_valide():
    fonction = Mock(return_value={"nb_pubs": 2})
    appel = AppelOutil(id="c1", nom="chercher_pubs_meta", arguments='{"marque": "Typology", "max_pubs": 5}')

    observation = executer_appel_outil(appel, outils_de_test(fonction))

    fonction.assert_called_once_with(marque="Typology", max_pubs=5)
    assert json.loads(observation) == {"nb_pubs": 2}


def test_valeur_par_defaut_appliquee():
    fonction = Mock(return_value={})
    appel = AppelOutil(id="c1", nom="chercher_pubs_meta", arguments='{"marque": "Typology"}')

    executer_appel_outil(appel, outils_de_test(fonction))

    fonction.assert_called_once_with(marque="Typology", max_pubs=10)


def test_outil_inconnu():
    fonction = Mock()
    appel = AppelOutil(id="c1", nom="chercher_pubs_linkedin", arguments="{}")

    observation = json.loads(executer_appel_outil(appel, outils_de_test(fonction)))

    assert "chercher_pubs_meta" in observation["erreur"]   # la liste des outils existants est donnée
    fonction.assert_not_called()


def test_argument_hors_bornes():
    fonction = Mock()
    appel = AppelOutil(id="c1", nom="chercher_pubs_meta", arguments='{"marque": "Typology", "max_pubs": 500}')

    observation = json.loads(executer_appel_outil(appel, outils_de_test(fonction)))

    assert "max_pubs" in observation["erreur"]
    fonction.assert_not_called()


def test_json_mal_forme():
    fonction = Mock()
    appel = AppelOutil(id="c1", nom="chercher_pubs_meta", arguments='{"marque": "Typology"')   # accolade manquante

    observation = json.loads(executer_appel_outil(appel, outils_de_test(fonction)))

    assert "erreur" in observation
    fonction.assert_not_called()


def test_creer_outils_injecte_le_client():
    client = Mock()
    outils = creer_outils(client)

    assert set(outils) == {"lire_page_web", "chercher_pubs_meta", "chercher_pubs_tiktok"}
    assert outils["chercher_pubs_meta"].fonction.keywords["client"] is client