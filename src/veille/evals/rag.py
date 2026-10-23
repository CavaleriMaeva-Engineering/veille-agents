"""Évaluation de la recherche (RAG) sur des cas annotés à la main.

Les cas (questions) sont dans evals/cas_rag.yaml ; les annotations (quels extraits sont pertinents pour
chaque question) sont dans evals/annotations_rag.json, écrites par un humain avec scripts/annoter_evals.py.
"""

import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from veille.evals.metriques import moyenne, precision_a_k, rang_reciproque, rappel_a_k
from veille.rag.documents import Morceau
from veille.rag.recherche import MoteurRecherche

DOSSIER_EVALS = Path("evals")
FICHIER_CAS = DOSSIER_EVALS / "cas_rag.yaml"
FICHIER_ANNOTATIONS = DOSSIER_EVALS / "annotations_rag.json"


class CasRAG(BaseModel):
    id: str
    question: str
    type: Literal["normal", "limite", "adverse"]
    marque: str | None = None
    attendu: Literal["reponse", "abstention"] = "reponse"   # adverse sans réponse dans l'historique : s'abstenir
    note: str = ""


class Annotation(BaseModel):
    pertinents: list[str]          # identifiants des morceaux jugés pertinents
    candidats: list[str] | None = None   # tous les morceaux montrés (les autres = jugés non pertinents)
    annote_par: str
    annote_le: str


POOL_PAR_MODE = 8
MODES_POOL = ("rerank", "bm25", "dense")


def pool_candidats(moteur: MoteurRecherche, cas: CasRAG, k: int = POOL_PAR_MODE) -> list[Morceau]:
    """Union des k premiers résultats de chaque méthode (pooling, comme les campagnes TREC), sans doublon.
    Même fonction pour l'annotation humaine et pour le juge : ils jugent exactement les mêmes candidats."""
    candidats: list[Morceau] = []
    for mode in MODES_POOL:
        for resultat in moteur.rechercher(cas.question, k=k, marque=cas.marque, mode=mode):
            if resultat.morceau.id not in {m.id for m in candidats}:
                candidats.append(resultat.morceau)
    return candidats


def charger_cas(chemin: Path = FICHIER_CAS) -> list[CasRAG]:
    return [CasRAG.model_validate(c) for c in yaml.safe_load(chemin.read_text(encoding="utf-8"))]


def charger_annotations(chemin: Path = FICHIER_ANNOTATIONS) -> dict[str, Annotation]:
    if not chemin.exists():
        return {}
    brut = json.loads(chemin.read_text(encoding="utf-8"))
    return {cle: Annotation.model_validate(valeur) for cle, valeur in brut.items()}


def enregistrer_annotations(annotations: dict[str, Annotation], chemin: Path = FICHIER_ANNOTATIONS) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    donnees = {cle: a.model_dump() for cle, a in sorted(annotations.items())}
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")


class ScoreMode(BaseModel):
    mode: str
    nb_cas: int
    precision: float     # moyenne de la précision@k
    rappel: float        # moyenne du rappel@k
    mrr: float
    premier_pertinent: float   # part des cas où le 1er résultat est pertinent (hit@1)


def evaluer_recherche(
    moteur: MoteurRecherche,
    cas: list[CasRAG],
    annotations: dict[str, Annotation],
    modes: list[str],
    k: int = 5,
) -> tuple[list[ScoreMode], list[dict]]:
    """Seuls les cas annotés avec au moins un pertinent comptent : sans pertinent, le rappel n'a pas de sens
    (les cas « abstention » s'évaluent sur la réponse, pas sur la recherche)."""
    evaluables = [c for c in cas if c.id in annotations and annotations[c.id].pertinents]
    scores, details = [], []
    for mode in modes:
        p, r, rr, h1 = [], [], [], []
        for c in evaluables:
            pertinents = set(annotations[c.id].pertinents)
            trouves = [res.morceau.id for res in moteur.rechercher(c.question, k=k, marque=c.marque, mode=mode)]
            p.append(precision_a_k(trouves, pertinents, k))
            r.append(rappel_a_k(trouves, pertinents, k))
            rr.append(rang_reciproque(trouves, pertinents))
            h1.append(1.0 if trouves[:1] and trouves[0] in pertinents else 0.0)
            details.append({"cas": c.id, "mode": mode, "precision": p[-1], "rappel": r[-1], "rr": rr[-1]})
        scores.append(ScoreMode(
            mode=mode, nb_cas=len(evaluables), precision=round(moyenne(p), 3), rappel=round(moyenne(r), 3),
            mrr=round(moyenne(rr), 3), premier_pertinent=round(moyenne(h1), 3),
        ))
    return scores, details
