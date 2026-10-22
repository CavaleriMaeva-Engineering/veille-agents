from datetime import date

from veille.agents.analyste import AnalyseMarque
from veille.agents.rapport import RapportVeille
from veille.agents.signaux import Signaux
from veille.storage.analyses import (
    charger_analyse,
    enregistrer_analyse,
    lister_analyses,
)


def fausse_analyse(marque: str = "Merci Handy", jour: date = date(2026, 10, 22)) -> AnalyseMarque:
    return AnalyseMarque(
        marque=marque,
        date=jour,
        execution_id="t-1",
        observations=['{"nb_pubs": 0}'],
        signaux=Signaux(nb_pubs={}, formats={}, pub_la_plus_durable=None, sources_en_erreur=[]),
        rapport=RapportVeille(
            marque=marque, produits_pousses=[], messages_et_promesses=[], offres=[],
            formats_et_plateformes=[], cible=[], donnees_manquantes=[],
        ),
    )


def test_aller_retour(tmp_path):
    analyse = fausse_analyse()

    chemin = enregistrer_analyse(analyse, dossier=tmp_path)

    assert chemin.name == "2026-10-22_merci-handy_t-1.json"
    assert charger_analyse(chemin) == analyse


def test_lister_dans_l_ordre(tmp_path):
    enregistrer_analyse(fausse_analyse(jour=date(2026, 10, 29)), dossier=tmp_path)
    enregistrer_analyse(fausse_analyse(jour=date(2026, 10, 22)), dossier=tmp_path)
    enregistrer_analyse(fausse_analyse(marque="Typology"), dossier=tmp_path)

    chemins = lister_analyses("Merci Handy", dossier=tmp_path)

    assert [c.name[:10] for c in chemins] == ["2026-10-22", "2026-10-29"]