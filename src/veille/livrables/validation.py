"""Validation humaine avant l'envoi Slack quand la confiance est basse (human-in-the-loop).

La confiance est évaluée par le code, à partir de faits vérifiables (échecs, sources en erreur, collectes
relancées, analyses périmées, rapport vide). Si elle est basse, le message n'est pas envoyé : il part dans
une file d'attente (un fichier par envoi), et un humain l'approuve ou le rejette avec scripts/valider.py.
"""

import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from veille.agents.analyste import AnalyseMarque
from veille.agents.rapport import SECTIONS_CONSTATS
from veille.agents.synthese import SyntheseVeille
from veille.storage.analyses import DOSSIER_SORTIES

DOSSIER_A_VALIDER = DOSSIER_SORTIES / "a_valider"
AGE_MAX_ANALYSE = timedelta(days=1)   # au-delà, l'analyse d'une marque n'est plus « la veille du jour »


class Confiance(BaseModel):
    haute: bool
    raisons: list[str]   # pourquoi elle est basse ; vide si elle est haute


class Envoi(BaseModel):
    id: str
    cree_le: datetime
    message: dict              # le message Slack prêt à partir, tel qu'il a été relu
    chemin_pdf: str | None
    raisons: list[str]
    statut: Literal["en_attente", "approuve", "rejete"] = "en_attente"
    decide_par: str | None = None
    decide_le: datetime | None = None
    motif: str | None = None


def evaluer_confiance(synthese: SyntheseVeille, analyses: list[AnalyseMarque], aujourd_hui: date) -> Confiance:
    raisons = [f"{marque} : analyse en échec" for marque in synthese.echecs]
    for analyse in analyses:
        if analyse.signaux.sources_en_erreur:
            erreurs = ", ".join(sorted(set(analyse.signaux.sources_en_erreur)))   # 3 pages en erreur = « site » une fois
            raisons.append(f"{analyse.marque} : source(s) en erreur ({erreurs})")
        if analyse.nb_collectes > 1:
            raisons.append(f"{analyse.marque} : collecte relancée ({analyse.nb_collectes} collectes)")
        if aujourd_hui - analyse.date > AGE_MAX_ANALYSE:
            raisons.append(f"{analyse.marque} : analyse périmée (du {analyse.date.isoformat()})")
        nb_pubs = sum(analyse.signaux.nb_pubs.values())
        nb_constats = sum(len(getattr(analyse.rapport, champ)) for champ in SECTIONS_CONSTATS)
        if nb_pubs and not nb_constats:
            raisons.append(f"{analyse.marque} : rapport vide malgré {nb_pubs} pub(s)")
    return Confiance(haute=not raisons, raisons=raisons)


def creer_envoi(message: dict, chemin_pdf: Path | None, raisons: list[str]) -> Envoi:
    return Envoi(
        id=uuid.uuid4().hex[:8], cree_le=datetime.now(), message=message,
        chemin_pdf=str(chemin_pdf) if chemin_pdf else None, raisons=raisons,
    )


def enregistrer_envoi(envoi: Envoi, dossier: Path = DOSSIER_A_VALIDER) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"{envoi.id}.json"
    chemin.write_text(envoi.model_dump_json(indent=2), encoding="utf-8")
    return chemin


def charger_envoi(identifiant: str, dossier: Path = DOSSIER_A_VALIDER) -> Envoi:
    chemin = dossier / f"{identifiant}.json"
    if not chemin.exists():
        raise ValueError(f"Aucun envoi {identifiant} dans {dossier}")
    return Envoi.model_validate_json(chemin.read_text(encoding="utf-8"))


def lister_en_attente(dossier: Path = DOSSIER_A_VALIDER) -> list[Envoi]:
    envois = [Envoi.model_validate_json(c.read_text(encoding="utf-8")) for c in sorted(dossier.glob("*.json"))]
    return sorted((e for e in envois if e.statut == "en_attente"), key=lambda e: e.cree_le)


def message_valide(message: dict, par: str) -> dict:
    """Le message envoyé garde la trace de la relecture humaine."""
    blocs = [*message.get("blocks", []), {
        "type": "context", "elements": [{"type": "mrkdwn", "text": f"Relu et validé par {par}"}],
    }]
    return {**message, "blocks": blocs}


def decider(
    identifiant: str,
    approuver: bool,
    par: str,
    envoyer: Callable[[dict], None],
    motif: str | None = None,
    dossier: Path = DOSSIER_A_VALIDER,
) -> Envoi:
    envoi = charger_envoi(identifiant, dossier)
    if envoi.statut != "en_attente":
        # Idempotence : un envoi déjà approuvé n'est jamais renvoyé, même si on relance la commande.
        raise ValueError(f"L'envoi {identifiant} est déjà {envoi.statut} (par {envoi.decide_par}).")
    if approuver:
        envoyer(message_valide(envoi.message, par))   # on n'enregistre « approuvé » qu'une fois l'envoi réussi
    envoi = envoi.model_copy(update={
        "statut": "approuve" if approuver else "rejete", "decide_par": par, "decide_le": datetime.now(), "motif": motif,
    })
    enregistrer_envoi(envoi, dossier)
    return envoi
