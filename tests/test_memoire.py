import json
from datetime import date
from unittest.mock import Mock

from test_rag import analyse, faux_encodeur, morceau
from test_superviseur import analyse_d_hier, collecte, config_de_test, signaux

from veille.agents import rapport as module_rapport
from veille.agents.changements import Changements
from veille.agents.memoire import (
    TAILLE_SOUVENIR,
    construire_rappel,
    formater_memoire,
    requete_depuis_collecte,
)
from veille.agents.rapport import RapportVeille
from veille.agents.superviseur import lancer_veille
from veille.rag.documents import Morceau
from veille.rag.recherche import MoteurRecherche
from veille.storage.analyses import enregistrer_analyse


def test_requete_construite_avec_les_textes_des_pubs_du_jour():
    observations = [json.dumps({"pubs": [{"textes": ["Coffret de Noël"]}]}), "pas du JSON"]
    assert requete_depuis_collecte(observations, "Typology") == "Typology Coffret de Noël"


def test_requete_generique_sans_pub():
    assert requete_depuis_collecte([], "Respire").startswith("Respire")


def test_filtres_date_et_type_appliques_avant_le_classement():
    hier = Morceau(id="h", texte="coffret", marque="Typology", type="pub", source="meta", date=date(2026, 10, 22))
    page = Morceau(id="p", texte="coffret", marque="Typology", type="page", source="site", date=date(2026, 10, 22))
    moteur = MoteurRecherche([hier, page, morceau("auj", "coffret")], faux_encodeur)   # morceau() : daté du 23

    resultats = moteur.rechercher("coffret", mode="hybride", avant=date(2026, 10, 23), types={"pub"})

    assert [r.morceau.id for r in resultats] == ["h"]


def test_rappel_ne_renvoie_que_les_pubs_de_la_marque(tmp_path):
    enregistrer_analyse(analyse(22), tmp_path)
    rappeler = construire_rappel([tmp_path], faux_encodeur)

    souvenirs = rappeler("Typology", "coffret de Noël")

    assert souvenirs and all(s.marque == "Typology" for s in souvenirs)
    assert {s.type for s in souvenirs} == {"pub"}                          # ni constats ni pages web
    assert rappeler("Respire", "coffret de Noël") == []


def test_memoire_formatee_avec_changements_et_souvenirs_coupes():
    long = Morceau(
        id="x", texte="a" * 1000, marque="Typology", type="pub", source="meta",
        date=date(2026, 10, 22), vu_le=[date(2026, 10, 20), date(2026, 10, 22)],
    )
    changements = Changements(comparable=True, nouvelles_pubs=["meta:9"], nouveaux_formats=["VIDEO"])

    texte = formater_memoire([long], changements)

    assert "1 nouvelle(s) pub(s)" in texte and "VIDEO" in texte
    assert "2026-10-20 → 2026-10-22" in texte
    assert "a" * TAILLE_SOUVENIR + "…" in texte and "a" * (TAILLE_SOUVENIR + 1) not in texte


def test_premiere_veille_signalee():
    assert "Pas de veille précédente comparable" in formater_memoire([], Changements(comparable=False))


def rapport_vide() -> RapportVeille:
    return RapportVeille(marque="Typology", produits_pousses=[], messages_et_promesses=[], offres=[],
                         formats_et_plateformes=[], cible=[], donnees_manquantes=[])


def lancer_avec_memoire(rappeler, precedente=None):
    rediger = Mock(return_value=rapport_vide())
    resultat = lancer_veille(
        config_de_test(), Mock(), Mock(), "essai", collecter=Mock(return_value=collecte()), rediger=rediger,
        enregistrer=Mock(), charger_precedente=lambda nom: precedente, rappeler=rappeler,
    )
    return resultat, rediger


def test_memoire_transmise_au_redacteur_quand_il_redige():
    rappeler = Mock(return_value=[morceau("souv", "Coffret vu la semaine dernière")])

    resultat, rediger = lancer_avec_memoire(rappeler)

    assert "Coffret vu la semaine dernière" in rediger.call_args.kwargs["memoire"]
    assert resultat.analyses[0].souvenirs == ["souv"]


def test_pas_de_recherche_dans_le_passe_quand_le_rapport_est_repris():
    rappeler = Mock()

    resultat, rediger = lancer_avec_memoire(rappeler, precedente=analyse_d_hier(signaux()))

    assert resultat.analyses[0].decision == "reutilise"
    rediger.assert_not_called()
    rappeler.assert_not_called()


def test_historique_ajoute_au_message_du_redacteur(monkeypatch):
    capture = {}

    def faux_generer(client, modele, messages, modele_sortie, **kwargs):
        capture["messages"] = messages
        return rapport_vide()

    monkeypatch.setattr(module_rapport, "generer_structure", faux_generer)
    module_rapport.rediger_rapport(Mock(), "m", "Typology", [], signaux(), "t", memoire="- coffret vu le 20/10")

    message = capture["messages"][1]["content"]
    assert "<historique>\n- coffret vu le 20/10\n</historique>" in message
