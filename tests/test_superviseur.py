from datetime import date, datetime
from unittest.mock import Mock

from veille.agents.analyste import AnalyseMarque, Collecte
from veille.agents.rapport import RapportVeille
from veille.agents.signaux import Signaux
from veille.agents.superviseur import MAX_COLLECTES, lancer_veille, raisons_de_relancer
from veille.settings import Config, Marque


def config_de_test(*noms: str) -> Config:
    return Config(
        marche="test", modele="modele",
        marques=[Marque(nom=nom, site=f"https://{nom.lower()}.com") for nom in noms or ("Typology",)],
        outils_actifs=["chercher_pubs_meta"],
    )


def signaux(ids=("meta:1",), erreurs=(), interrogees=("meta",)) -> Signaux:
    return Signaux(
        nb_pubs={"meta": len(ids)} if ids else {}, formats={}, pub_la_plus_durable=None,
        sources_en_erreur=list(erreurs), sources_collectees=["meta"] if ids else [],
        sources_interrogees=list(interrogees), ids_pubs=list(ids), pages_destination=[],
    )


def collecte(**kwargs) -> Collecte:
    return Collecte(observations=["{}"], signaux=signaux(**kwargs))


def rapport(marque: str = "Typology") -> RapportVeille:
    return RapportVeille(marque=marque, produits_pousses=[], messages_et_promesses=[], offres=[],
                         formats_et_plateformes=[], cible=[], donnees_manquantes=[])


def analyse_d_hier(sig: Signaux) -> AnalyseMarque:
    return AnalyseMarque(
        marque="Typology", date=date(2026, 10, 22), horodatage=datetime(2026, 10, 22, 9, 0, 0),
        execution_id="hier", observations=[], signaux=sig, rapport=rapport(),
    )


def lancer(collecter, precedente=None, config=None):
    rediger, enregistrer = Mock(return_value=rapport()), Mock()
    resultat = lancer_veille(
        config or config_de_test(), Mock(), Mock(), "essai",
        collecter=collecter, rediger=rediger, enregistrer=enregistrer, charger_precedente=lambda nom: precedente,
    )
    return resultat, rediger, enregistrer


# --- Décision 1 : relancer une collecte insuffisante ---

def test_zero_pub_sans_erreur_ne_justifie_pas_de_relance():
    assert raisons_de_relancer(signaux(ids=()), ["chercher_pubs_meta"]) == []


def test_erreur_du_site_ne_justifie_pas_de_relance():
    assert raisons_de_relancer(signaux(erreurs=("site",)), ["chercher_pubs_meta", "lire_page_web"]) == []


def test_outil_oublie_par_l_agent_justifie_une_relance():
    assert raisons_de_relancer(signaux(interrogees=()), ["chercher_pubs_meta"]) == ["meta jamais interrogée"]


def test_relance_apres_une_erreur_puis_succes():
    collecter = Mock(side_effect=[collecte(ids=(), erreurs=("meta",)), collecte()])

    resultat, _, _ = lancer(collecter)

    assert collecter.call_count == 2
    assert resultat.analyses[0].nb_collectes == 2


def test_pas_plus_de_max_collectes():
    collecter = Mock(return_value=collecte(ids=(), erreurs=("meta",)))

    resultat, _, _ = lancer(collecter)

    assert collecter.call_count == MAX_COLLECTES
    assert resultat.analyses[0].nb_collectes == MAX_COLLECTES


# --- Décision 2 : rédiger seulement s'il y a du nouveau ---

def test_rien_de_nouveau_rapport_reutilise_sans_appel_llm():
    hier = analyse_d_hier(signaux())

    resultat, rediger, _ = lancer(Mock(return_value=collecte()), precedente=hier)

    rediger.assert_not_called()
    assert resultat.analyses[0].decision == "reutilise"
    assert resultat.analyses[0].rapport == hier.rapport


def test_changement_significatif_rapport_redige():
    hier = analyse_d_hier(signaux(ids=("meta:1",)))

    resultat, rediger, _ = lancer(Mock(return_value=collecte(ids=("meta:2",))), precedente=hier)

    rediger.assert_called_once()
    assert resultat.analyses[0].decision == "redige"
    assert resultat.analyses[0].changements.nouvelles_pubs == ["meta:2"]


def test_premiere_veille_rapport_redige():
    resultat, rediger, _ = lancer(Mock(return_value=collecte()))

    rediger.assert_called_once()
    assert resultat.analyses[0].decision == "redige"
    assert not resultat.analyses[0].changements.comparable


# --- Décision 3 : gérer les échecs ---

def test_une_marque_en_echec_n_arrete_pas_les_autres():
    def collecter(**kwargs):
        if kwargs["marque"].nom == "Horace":
            raise RuntimeError("panne simulée")
        return collecte()

    resultat, _, enregistrer = lancer(collecter, config=config_de_test("Typology", "Horace"))

    assert [a.marque for a in resultat.analyses] == ["Typology"]
    assert "Horace" in resultat.echecs
    enregistrer.assert_called_once()   # seule l'analyse réussie est enregistrée


def test_outils_actifs_et_identifiants_transmis():
    collecter = Mock(return_value=collecte())

    lancer(collecter)

    appel = collecter.call_args.kwargs
    assert appel["outils_actifs"] == ["chercher_pubs_meta"]
    assert appel["execution_id"] == "essai-typology"
