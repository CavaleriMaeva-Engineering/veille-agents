from datetime import date, datetime
from unittest.mock import Mock

from veille.agents.analyste import AnalyseMarque
from veille.agents.rapport import RapportVeille
from veille.agents.signaux import Signaux
from veille.agents.superviseur import lancer_veille
from veille.settings import Config, Marque


def config_de_test() -> Config:
    return Config(
        marche="test", modele="modele",
        marques=[Marque(nom="Typology", site="https://www.typology.com"), Marque(nom="Horace", site="https://horace.com")],
        outils_actifs=["chercher_pubs_meta"],
    )


def fausse_analyse(marque: str) -> AnalyseMarque:
    return AnalyseMarque(
        marque=marque, date=date(2026, 10, 23), horodatage=datetime(2026, 10, 23, 9, 0, 0), execution_id="t", observations=[],
        signaux=Signaux(nb_pubs={}, formats={}, pub_la_plus_durable=None, sources_en_erreur=[]),
        rapport=RapportVeille(marque=marque, produits_pousses=[], messages_et_promesses=[], offres=[],
                              formats_et_plateformes=[], cible=[], donnees_manquantes=[]),
    )


def faux_analyste(**kwargs) -> AnalyseMarque:
    if kwargs["marque"].nom == "Horace":
        raise RuntimeError("panne simulée")
    return fausse_analyse(kwargs["marque"].nom)


def test_une_marque_en_echec_n_arrete_pas_les_autres():
    enregistrer = Mock()

    resultat = lancer_veille(config_de_test(), Mock(), Mock(), "essai", analyser=faux_analyste, enregistrer=enregistrer)

    assert [a.marque for a in resultat.analyses] == ["Typology"]
    assert "Horace" in resultat.echecs
    enregistrer.assert_called_once()   # seule l'analyse réussie est enregistrée


def test_outils_actifs_et_identifiants_transmis():
    analyser = Mock(side_effect=lambda **kwargs: fausse_analyse(kwargs["marque"].nom))

    lancer_veille(config_de_test(), Mock(), Mock(), "essai", analyser=analyser, enregistrer=Mock())

    premier_appel = analyser.call_args_list[0].kwargs
    assert premier_appel["outils_actifs"] == ["chercher_pubs_meta"]
    assert premier_appel["execution_id"] == "essai-typology"