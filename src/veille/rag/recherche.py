"""Recherche hybride : BM25 + dense fusionnés par RRF, puis reranking par cross-encoder."""

from collections import defaultdict
from collections.abc import Callable

from pydantic import BaseModel

from veille.rag.bm25 import BM25
from veille.rag.documents import Morceau
from veille.rag.index import Encodeur, IndexVectoriel

type Reranker = Callable[[str, list[str]], list[float]]

K_RRF = 60                 # constante usuelle de la fusion par rang réciproque
NB_CANDIDATS = 20          # combien de candidats chaque méthode passe à l'étape suivante
MODES = ("bm25", "dense", "hybride", "rerank")


def fusion_rrf(classements: list[list[int]], k: int = K_RRF) -> dict[int, float]:
    """Reciprocal Rank Fusion : on additionne 1 / (k + rang). Seuls les rangs comptent, pas les scores,
    ce qui évite de devoir rendre comparables un score BM25 (non borné) et un cosinus (entre -1 et 1)."""
    scores: dict[int, float] = defaultdict(float)
    for classement in classements:
        for rang, indice in enumerate(classement, start=1):
            scores[indice] += 1 / (k + rang)
    return dict(scores)


class Resultat(BaseModel):
    morceau: Morceau
    score: float
    rangs: dict[str, int]   # rang (à partir de 1) dans chaque classement où le morceau apparaît


class MoteurRecherche:
    def __init__(
        self,
        morceaux: list[Morceau],
        encodeur: Encodeur,
        reranker: Reranker | None = None,
        nb_candidats: int = NB_CANDIDATS,
    ) -> None:
        self.morceaux = morceaux
        textes = [m.texte for m in morceaux]
        self.bm25 = BM25(textes)
        self.dense = IndexVectoriel(textes, encodeur)
        self.reranker = reranker
        self.nb_candidats = nb_candidats

    def _classer(self, question: str, marque: str | None) -> tuple[dict[str, list[int]], dict[str, dict[int, float]]]:
        # Filtre par métadonnées AVANT le classement : on ne cherche que dans les morceaux de la marque demandée.
        autorises = [i for i, m in enumerate(self.morceaux) if marque is None or m.marque.lower() == marque.lower()]
        s_bm25 = self.bm25.scores(question)
        s_dense = self.dense.scores(question)

        bm25 = sorted((i for i in autorises if s_bm25[i] > 0), key=lambda i: -s_bm25[i])[: self.nb_candidats]
        dense = sorted(autorises, key=lambda i: -s_dense[i])[: self.nb_candidats]
        rrf = fusion_rrf([bm25, dense])
        hybride = sorted(rrf, key=lambda i: -rrf[i])[: self.nb_candidats]

        ordres = {"bm25": bm25, "dense": dense, "hybride": hybride}
        scores = {
            "bm25": {i: s_bm25[i] for i in bm25},
            "dense": {i: float(s_dense[i]) for i in dense},
            "hybride": {i: rrf[i] for i in hybride},
        }

        if self.reranker is not None and hybride:
            # Le cross-encoder lit la question ET le morceau ensemble : plus précis, mais un appel par paire,
            # donc réservé aux candidats déjà filtrés par la recherche hybride.
            s_rerank = self.reranker(question, [self.morceaux[i].texte for i in hybride])
            scores["rerank"] = dict(zip(hybride, s_rerank, strict=True))
            ordres["rerank"] = sorted(hybride, key=lambda i: -scores["rerank"][i])
        return ordres, scores

    def rechercher(self, question: str, k: int = 5, marque: str | None = None, mode: str = "rerank") -> list[Resultat]:
        if mode not in MODES:
            raise ValueError(f"mode inconnu : {mode} (attendu : {', '.join(MODES)})")
        if mode == "rerank" and self.reranker is None:
            raise ValueError("aucun reranker fourni")
        ordres, scores = self._classer(question, marque)
        rangs = {nom: {i: r for r, i in enumerate(ordre, start=1)} for nom, ordre in ordres.items()}
        return [
            Resultat(
                morceau=self.morceaux[i],
                score=round(float(scores[mode][i]), 4),
                rangs={nom: r[i] for nom, r in rangs.items() if i in r},
            )
            for i in ordres.get(mode, [])[:k]
        ]
