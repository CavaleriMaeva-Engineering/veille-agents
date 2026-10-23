"""Index vectoriel « flat » : similarité cosinus exacte avec NumPy.

Quelques centaines de morceaux : comparer la question à tous est instantané.
À partir de ~100 000 morceaux, on passerait à un index approximatif (HNSW) ou à pgvector.
"""

from collections.abc import Callable

import numpy as np

type Encodeur = Callable[[list[str]], np.ndarray]


def normaliser(vecteurs: np.ndarray) -> np.ndarray:
    normes = np.linalg.norm(vecteurs, axis=1, keepdims=True)
    return vecteurs / np.where(normes == 0, 1, normes)


class IndexVectoriel:
    def __init__(self, textes: list[str], encodeur: Encodeur) -> None:
        self.encodeur = encodeur
        # vecteurs normalisés une fois pour toutes : le cosinus devient un simple produit scalaire
        self.vecteurs = normaliser(np.asarray(encodeur(textes), dtype=float)) if textes else None

    def scores(self, requete: str) -> np.ndarray:
        if self.vecteurs is None:
            return np.zeros(0)
        question = normaliser(np.asarray(self.encodeur([requete]), dtype=float))[0]
        return self.vecteurs @ question
