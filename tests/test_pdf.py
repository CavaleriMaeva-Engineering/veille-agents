from datetime import date, datetime

from veille.agents.analyste import AnalyseMarque
from veille.agents.rapport import Constat, RapportVeille
from veille.agents.signaux import Signaux
from veille.agents.synthese import SignauxMarche, SyntheseMarche, SyntheseVeille
from veille.livrables.pdf import generer_pdf, nettoyer

MOMENT = datetime(2026, 10, 23, 14, 0, 0)


def fausse_synthese() -> SyntheseVeille:
    return SyntheseVeille(
        date=date(2026, 10, 23), horodatage=MOMENT, execution_id="t", marques_analysees=["Typology"],
        echecs={"Horace": "panne"},
        signaux=SignauxMarche(nb_pubs_par_marque={"Typology": 5}, formats={"VIDEO": 5},
                              classement_pubs_durables=[], marques_sans_pub=[]),
        synthese=SyntheseMarche(tendances_communes=["Calendriers de l'Avent & coffrets"], positionnements=[],
                                differences_notables=[], limites=[]),
    )


def fausse_analyse() -> AnalyseMarque:
    return AnalyseMarque(
        marque="Typology", date=date(2026, 10, 23), horodatage=MOMENT, execution_id="t", observations=[],
        signaux=Signaux(nb_pubs={"meta": 5}, formats={}, pub_la_plus_durable=None, sources_en_erreur=[]),
        rapport=RapportVeille(
            marque="Typology", produits_pousses=[Constat(affirmation="Crème anti\u2011rides", sources=["meta"])],
            messages_et_promesses=[], offres=[], formats_et_plateformes=[], cible=[], donnees_manquantes=[],
        ),
    )


def test_pdf_genere(tmp_path):
    chemin = generer_pdf(fausse_synthese(), [fausse_analyse()], tmp_path / "rapport.pdf")

    assert chemin.read_bytes().startswith(b"%PDF")   # la signature de tout fichier PDF


def test_nettoyer():
    assert nettoyer("anti\u2011rides & <promo>") == "anti-rides &amp; &lt;promo&gt;"