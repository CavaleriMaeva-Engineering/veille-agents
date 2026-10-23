"""Évaluations sur les vraies veilles enregistrées : le rédacteur (ancrage, sources) et l'agent (trajectoire)."""

import json

from pydantic import BaseModel

from veille.agents.analyste import AnalyseMarque
from veille.agents.rapport import SECTIONS_CONSTATS
from veille.evals.metriques import moyenne
from veille.garde_fous import verifier_ancrage


class ScoreRedaction(BaseModel):
    nb_rapports: int
    nb_constats: int
    taux_ancrage: float          # part des constats dont tous les chiffres sont dans les données
    constats_par_rapport: float
    rapports_vides_malgre_pubs: int


def evaluer_redactions(analyses: list[AnalyseMarque]) -> ScoreRedaction:
    redigees = [a for a in analyses if a.decision == "redige"]
    nb_constats, nb_ancres, vides = 0, 0, 0
    for analyse in redigees:
        total = sum(len(getattr(analyse.rapport, champ)) for champ in SECTIONS_CONSTATS)
        verifie, _ = verifier_ancrage(analyse.rapport, analyse.observations, analyse.signaux)
        nb_constats += total
        nb_ancres += sum(len(getattr(verifie, champ)) for champ in SECTIONS_CONSTATS)
        if total == 0 and sum(analyse.signaux.nb_pubs.values()):
            vides += 1
    return ScoreRedaction(
        nb_rapports=len(redigees), nb_constats=nb_constats,
        taux_ancrage=round(nb_ancres / nb_constats, 3) if nb_constats else 0.0,
        constats_par_rapport=round(nb_constats / len(redigees), 1) if redigees else 0.0,
        rapports_vides_malgre_pubs=vides,
    )


class ScoreAgent(BaseModel):
    nb_collectes: int
    taux_succes: float            # réponse finale, sans relance, sans source de pubs en erreur, sans appel refusé
    tours_moyens: float
    tokens_moyens: float
    taux_limite_tours: float
    taux_relance: float
    appels_refuses: int


def succes(analyse: AnalyseMarque) -> bool:
    t = analyse.trajectoire
    return (
        t is not None and t.arret == "reponse_finale" and analyse.nb_collectes == 1
        and not set(analyse.signaux.sources_en_erreur) & {"meta", "tiktok"}
        and not any("non autorisée" in a or "budget" in a for a in analyse.alertes)
    )


def evaluer_trajectoires(analyses: list[AnalyseMarque]) -> ScoreAgent:
    avec = [a for a in analyses if a.trajectoire is not None]
    return ScoreAgent(
        nb_collectes=len(avec),
        taux_succes=round(moyenne([1.0 if succes(a) else 0.0 for a in avec]), 3),
        tours_moyens=round(moyenne([a.trajectoire.tours for a in avec]), 1),
        tokens_moyens=round(moyenne([a.trajectoire.tokens for a in avec])),
        taux_limite_tours=round(moyenne([1.0 if a.trajectoire.arret == "limite_tours" else 0.0 for a in avec]), 3),
        taux_relance=round(moyenne([1.0 if a.nb_collectes > 1 else 0.0 for a in avec]), 3),
        appels_refuses=sum(1 for a in avec for alerte in a.alertes if "non autorisée" in alerte or "budget" in alerte),
    )


def tableau(lignes: list[BaseModel]) -> str:
    """Un tableau Markdown à partir de modèles Pydantic de même type."""
    if not lignes:
        return "(aucune donnée)"
    colonnes = list(type(lignes[0]).model_fields)
    entete = "| " + " | ".join(colonnes) + " |\n| " + " | ".join("---" for _ in colonnes) + " |"
    corps = "\n".join(
        "| " + " | ".join(json.dumps(getattr(ligne, c), ensure_ascii=False).strip('"') for c in colonnes) + " |"
        for ligne in lignes
    )
    return f"{entete}\n{corps}"
