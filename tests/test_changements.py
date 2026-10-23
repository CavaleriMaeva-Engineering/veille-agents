from veille.agents.changements import comparer
from veille.agents.signaux import Signaux


def signaux(ids, formats=None, pages=None, sources=("meta",)) -> Signaux:
    return Signaux(
        nb_pubs={}, formats=formats or {}, pub_la_plus_durable=None, sources_en_erreur=[],
        sources_collectees=list(sources), ids_pubs=ids, pages_destination=pages or [],
    )


def test_premiere_veille_tout_est_nouveau():
    resultat = comparer(signaux(["meta:1"]), None)
    assert not resultat.comparable and resultat.significatif


def test_ancienne_analyse_sans_ids_pas_comparable():
    resultat = comparer(signaux(["meta:1"]), signaux(None))
    assert not resultat.comparable


def test_memes_pubs_pas_de_changement():
    resultat = comparer(signaux(["meta:1", "meta:2"]), signaux(["meta:1", "meta:2"]))
    assert resultat.score == 0 and not resultat.significatif


def test_pubs_renouvelees_changement_significatif():
    resultat = comparer(signaux(["meta:2", "meta:3", "meta:4", "meta:5"]), signaux(["meta:1", "meta:2", "meta:3"]))
    assert resultat.nouvelles_pubs == ["meta:4", "meta:5"]
    assert resultat.pubs_disparues == ["meta:1"]
    assert resultat.score == 0.6 and resultat.significatif


def test_nouvelle_page_suffit():
    resultat = comparer(
        signaux(["meta:1"], pages=["https://x.com/coffret"]), signaux(["meta:1"], pages=["https://x.com/creme"])
    )
    assert resultat.nouvelles_pages == ["https://x.com/coffret"] and resultat.significatif


def test_source_en_panne_ne_fait_pas_disparaitre_ses_pubs():
    aujourd_hui = signaux(["tiktok:9"], sources=["tiktok"])            # Meta a planté
    hier = signaux(["meta:1", "meta:2", "tiktok:9"], sources=["meta", "tiktok"])
    resultat = comparer(aujourd_hui, hier)
    assert resultat.pubs_disparues == [] and not resultat.significatif