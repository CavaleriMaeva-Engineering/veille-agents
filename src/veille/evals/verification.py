"""Garde-fous sur les évals qui tournent en CI : sans LLM, sans modèle local, sans réseau, sans clé (PJ17).

Ce que ce module vérifie, et ce qu'il ne vérifie pas :
- il contrôle que le **jeu d'évals** est sain (assez de cas, tous annotés, types présents) ;
- il recalcule les chiffres des **derniers relevés commités** (recherche et juge) et échoue s'ils passent sous un seuil ;
- il ne relance PAS la recherche ni le juge : cela demande le corpus (sorties/, hors de git), des modèles
  PyTorch et des appels Groq. Une régression de code n'est donc détectée que si quelqu'un relance les évals
  en local et commite le nouveau relevé. Les tests unitaires (pytest) couvrent, eux, le code des métriques.
"""

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from veille.evals.juge import Paire, mesurer_accord
from veille.evals.metriques import moyenne
from veille.evals.rag import (
    DOSSIER_EVALS,
    Annotation,
    CasRAG,
    charger_annotations,
    charger_cas,
)

# Seuils choisis avec une marge sous le dernier relevé (23/10/2026), pour qu'un bruit ne casse pas la CI
# mais qu'une vraie dégradation la casse. À relever quand les évals s'améliorent durablement.
NB_CAS_MIN, NB_CAS_MAX = 20, 30
RERANK_RAPPEL_MIN = 0.65        # relevé : 0,735 (rappel@5 du reranking)
RERANK_MRR_MIN = 0.90           # relevé : 0,975
KAPPA_JUGE_MIN = 0.80           # « excellent » sur l'échelle du rapport de calibration ; relevé : 0,992
CHANGEMENT_POSITION_MAX = 0.10  # part des verdicts du juge qui changent si l'on inverse l'ordre ; relevé : 0,03


@dataclass(frozen=True)
class Controle:
    nom: str
    ok: bool
    detail: str


def verifier_jeu(cas: list[CasRAG], annotations: dict[str, Annotation]) -> list[Controle]:
    ids = [c.id for c in cas]
    types = {c.type for c in cas}
    sans_annotation = sorted(set(ids) - set(annotations))
    orphelines = sorted(set(annotations) - set(ids))
    abstention_avec_pertinents = sorted(
        c.id for c in cas if c.attendu == "abstention" and annotations.get(c.id) and annotations[c.id].pertinents
    )
    sans_auteur = sorted(i for i, a in annotations.items() if not a.annote_par.strip())
    return [
        Controle("nombre de cas", NB_CAS_MIN <= len(cas) <= NB_CAS_MAX,
                 f"{len(cas)} cas (attendu entre {NB_CAS_MIN} et {NB_CAS_MAX})"),
        Controle("identifiants uniques", len(set(ids)) == len(ids), f"{len(ids) - len(set(ids))} doublon(s)"),
        Controle("trois types de cas", types == {"normal", "limite", "adverse"}, f"types présents : {sorted(types)}"),
        Controle("tous les cas sont annotés", not sans_annotation, f"sans annotation : {sans_annotation or 'aucun'}"),
        Controle("aucune annotation orpheline", not orphelines, f"annotations sans cas : {orphelines or 'aucune'}"),
        Controle("annotations signées", not sans_auteur, f"sans auteur : {sans_auteur or 'aucune'}"),
        Controle("abstention cohérente", not abstention_avec_pertinents,
                 f"cas à abstention qui ont pourtant des extraits pertinents : {abstention_avec_pertinents or 'aucun'}"),
    ]


def moyennes_par_mode(details: list[dict]) -> dict[str, dict[str, float]]:
    """details = lignes {cas, mode, precision, rappel, rr} écrites par scripts/evaluer.py."""
    groupes: dict[str, list[dict]] = defaultdict(list)
    for ligne in details:
        groupes[ligne["mode"]].append(ligne)
    return {
        mode: {"rappel": moyenne([x["rappel"] for x in lignes]), "mrr": moyenne([x["rr"] for x in lignes])}
        for mode, lignes in groupes.items()
    }


def verifier_recherche(details: list[dict]) -> list[Controle]:
    scores = moyennes_par_mode(details)
    if not {"rerank", "hybride"} <= set(scores):
        return [Controle("relevé de recherche complet", False, f"modes présents : {sorted(scores)}")]
    rerank, hybride = scores["rerank"], scores["hybride"]
    return [
        Controle("rappel@5 du reranking", rerank["rappel"] >= RERANK_RAPPEL_MIN,
                 f"{rerank['rappel']:.3f} (seuil {RERANK_RAPPEL_MIN})"),
        Controle("MRR du reranking", rerank["mrr"] >= RERANK_MRR_MIN, f"{rerank['mrr']:.3f} (seuil {RERANK_MRR_MIN})"),
        Controle("le reranking apporte quelque chose", rerank["rappel"] >= hybride["rappel"],
                 f"rappel@5 reranking {rerank['rappel']:.3f} contre hybride {hybride['rappel']:.3f}"),
    ]


def verifier_juge(paires: list[Paire]) -> list[Controle]:
    accord = mesurer_accord(paires)
    return [
        Controle("kappa du juge avec l'humain", accord.kappa >= KAPPA_JUGE_MIN,
                 f"{accord.kappa:.3f} (seuil {KAPPA_JUGE_MIN}) sur {accord.nb_coherentes} paires cohérentes"),
        Controle("stabilité du juge à l'inversion de l'ordre", accord.taux_changement_position <= CHANGEMENT_POSITION_MAX,
                 f"{accord.taux_changement_position:.3f} (plafond {CHANGEMENT_POSITION_MAX})"),
    ]


def dernier_releve(dossier: Path, motif: str) -> Path | None:
    """Le plus récent : les noms commencent par un horodatage ISO, donc l'ordre alphabétique est l'ordre du temps."""
    fichiers = sorted(dossier.glob(motif))
    return fichiers[-1] if fichiers else None


def verifier_tout(dossier_evals: Path = DOSSIER_EVALS) -> list[Controle]:
    controles = verifier_jeu(
        charger_cas(dossier_evals / "cas_rag.yaml"), charger_annotations(dossier_evals / "annotations_rag.json")
    )
    resultats = dossier_evals / "resultats"

    details = dernier_releve(resultats, "*_details.json")
    if details is None:
        controles.append(Controle("relevé de recherche présent", False, f"aucun *_details.json dans {resultats}"))
    else:
        controles += [
            Controle(c.nom, c.ok, f"{c.detail} · {details.name}")
            for c in verifier_recherche(json.loads(details.read_text(encoding="utf-8")))
        ]

    paires = dernier_releve(resultats, "*_juge_paires.json")
    if paires is None:
        controles.append(Controle("relevé du juge présent", False, f"aucun *_juge_paires.json dans {resultats}"))
    else:
        donnees = [Paire.model_validate(p) for p in json.loads(paires.read_text(encoding="utf-8"))]
        controles += [Controle(c.nom, c.ok, f"{c.detail} · {paires.name}") for c in verifier_juge(donnees)]
    return controles


def formater(controles: list[Controle]) -> str:
    return "\n".join(f"{'OK  ' if c.ok else 'ÉCHEC'}  {c.nom} : {c.detail}" for c in controles)
