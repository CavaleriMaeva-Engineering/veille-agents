import json

from veille.agents.signaux import calculer_signaux, extraire_resultats, sans_parametres

PUBS_META = {"marque": "Typology", "nb_pubs": 2, "pubs": [
    {"textes": ["Crème premières rides"], "duree_jours": 282, "format": "DCO",
     "lien": "https://www.typology.com/creme?utm_source=facebook"},
    {"textes": ["Calendrier de l'Avent"], "duree_jours": 10, "format": "VIDEO", "lien": None},
]}
PUBS_TIKTOK = {"marque": "Typology", "nb_pubs": 1, "pubs": [
    {"textes": ["Calendrier de l'Avent"], "duree_jours": 14, "format": "VIDEO", "lien": None},
]}


def test_signaux_calcules():
    resultats = [("chercher_pubs_meta", PUBS_META), ("chercher_pubs_tiktok", PUBS_TIKTOK)]

    signaux = calculer_signaux(resultats)

    assert signaux.nb_pubs == {"meta": 2, "tiktok": 1}
    assert signaux.formats == {"DCO": 1, "VIDEO": 2}
    assert signaux.pub_la_plus_durable.duree_jours == 282
    assert signaux.pub_la_plus_durable.source == "meta"
    assert signaux.pub_la_plus_durable.lien == "https://www.typology.com/creme"
    assert signaux.sources_en_erreur == []


def test_source_en_erreur():
    resultats = [("chercher_pubs_meta", PUBS_META), ("chercher_pubs_tiktok", {"erreur": "indisponible"})]

    signaux = calculer_signaux(resultats)

    assert signaux.sources_en_erreur == ["tiktok"]
    assert "tiktok" not in signaux.nb_pubs


def test_aucune_pub():
    signaux = calculer_signaux([("lire_page_web", {"url": "https://x.fr", "texte": "..."})])

    assert signaux.pub_la_plus_durable is None
    assert signaux.nb_pubs == {}


def test_extraire_resultats_relie_outil_et_resultat():
    messages = [
        {"role": "user", "content": "Marque : Typology"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "chercher_pubs_meta", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": json.dumps(PUBS_META)},
    ]

    resultats = extraire_resultats(messages)

    assert resultats == [("chercher_pubs_meta", PUBS_META)]


def test_sans_parametres():
    assert sans_parametres("https://www.typology.com/p?utm_source=tiktok&x=1") == "https://www.typology.com/p"
    assert sans_parametres(None) is None


def test_sources_collectees():
    resultats = [
        ("chercher_pubs_meta", PUBS_META),
        ("chercher_pubs_tiktok", {"erreur": "indisponible"}),
        ("lire_page_web", {"url": "https://x.fr", "texte": "..."}),
    ]

    assert calculer_signaux(resultats).sources_collectees == ["meta", "site"]


def test_source_sans_pub_non_collectee():
    resultats = [("chercher_pubs_meta", {"marque": "X", "nb_pubs": 0, "pubs": []})]

    assert calculer_signaux(resultats).sources_collectees == []