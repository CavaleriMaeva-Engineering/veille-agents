from datetime import date, datetime

import httpx

from veille.agents.signaux import PubDurable
from veille.agents.synthese import (
    PubDurableMarque,
    SignauxMarche,
    SyntheseMarche,
    SyntheseVeille,
)
from veille.livrables.slack import construire_message, envoyer_slack, tronquer


def fausse_synthese() -> SyntheseVeille:
    durables = [
        PubDurableMarque(marque=f"Marque{i}", pub=PubDurable(source="meta", texte="Promo <-50%> & cadeau", duree_jours=100 - i, lien=None))
        for i in range(5)
    ]
    return SyntheseVeille(
        date=date(2026, 10, 23), horodatage=datetime(2026, 10, 23, 14, 0), execution_id="t",
        marques_analysees=["Marque0"], echecs={"Horace": "panne"},
        signaux=SignauxMarche(nb_pubs_par_marque={"Marque0": 5}, formats={}, classement_pubs_durables=durables,
                              marques_sans_pub=["Respire"]),
        synthese=SyntheseMarche(tendances_communes=["t1", "t2", "t3", "t4"], positionnements=[],
                                differences_notables=[], limites=[]),
    )


def test_message_court_et_echappe():
    message = construire_message(fausse_synthese())
    texte = str(message["blocks"])

    assert message["text"] == "Veille publicitaire du 23/10/2026"
    assert "Marque2" in texte and "Marque3" not in texte   # 3 pubs gagnantes au plus
    assert "t4" not in texte                                  # 3 tendances au plus
    assert "&lt;-50%&gt; &amp; cadeau" in texte               # texte externe neutralisé
    assert "Respire" in texte and "Horace" in texte           # couverture complète


def test_tronquer():
    assert tronquer("a" * 200, 10) == "a" * 9 + "…"
    assert tronquer(None) == ""


def test_envoyer_slack(monkeypatch):
    envoyes = []

    def faux_post(url, json, timeout):
        envoyes.append((url, json))
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", faux_post)

    envoyer_slack({"text": "coucou"}, "https://hooks.slack.test/xyz")

    assert envoyes == [("https://hooks.slack.test/xyz", {"text": "coucou"})]