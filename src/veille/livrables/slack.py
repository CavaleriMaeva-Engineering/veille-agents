from pathlib import Path

import httpx

from veille.agents.synthese import SyntheseVeille
from veille.reseau import appeler_avec_tentatives


def echapper(texte: str) -> str:
    return texte.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tronquer(texte: str | None, longueur: int = 90) -> str:
    texte = (texte or "").replace("\n", " ").strip()
    return texte if len(texte) <= longueur else texte[: longueur - 1] + "…"


def puces(lignes: list[str]) -> str:
    return "\n".join(f"• {ligne}" for ligne in lignes) or "• aucune"


def construire_message(synthese: SyntheseVeille, chemin_pdf: Path | None = None) -> dict:
    signaux, s = synthese.signaux, synthese.synthese
    titre = f"Veille publicitaire du {synthese.horodatage:%d/%m/%Y}"
    pubs = puces([f"*{echapper(m)}* : {n} pubs actives" for m, n in signaux.nb_pubs_par_marque.items()])
    gagnantes = puces([
        f"*{echapper(d.marque)}* : {d.pub.duree_jours} jours. « {echapper(tronquer(d.pub.texte))} »"
        for d in signaux.classement_pubs_durables[:3]
    ])
    tendances = puces([echapper(t) for t in s.tendances_communes[:3]])
    couverture = f"Sans pub active : {', '.join(signaux.marques_sans_pub) or 'aucune'}"
    if synthese.echecs:
        couverture += f" · Non analysées : {', '.join(synthese.echecs)}"
    if chemin_pdf:
        couverture += f" · Rapport complet : {chemin_pdf.name}"

    return {
        "text": titre,   # texte de secours : notifications et lecteurs d'écran
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": titre}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Pubs actives*\n{pubs}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Pubs les plus durables*\n{gagnantes}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Tendances*\n{tendances}"}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": echapper(couverture)}]},
        ],
    }


def envoyer_slack(message: dict, url: str) -> None:
    def envoyer() -> None:
        httpx.post(url, json=message, timeout=10).raise_for_status()

    appeler_avec_tentatives(envoyer, max_tentatives=3)