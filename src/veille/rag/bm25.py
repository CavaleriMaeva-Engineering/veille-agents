"""BM25 écrit à la main : la recherche par mots-clés, celle qui trouve les mots exacts (noms de produits, prix)."""

import math
import re
import unicodedata
from collections import Counter

MOTS_VIDES = {
    "le", "la", "les", "un", "une", "des", "du", "de", "et", "ou", "en", "au", "aux", "pour", "par",
    "sur", "avec", "dans", "est", "sont", "qui", "que", "quoi", "quel", "quelle", "quels", "quelles",
    "ce", "ces", "cette", "son", "sa", "ses", "leur", "leurs", "il", "elle", "ils", "elles", "pas", "plus",
}


def tokeniser(texte: str) -> list[str]:
    texte = unicodedata.normalize("NFKD", texte.lower())
    texte = "".join(c for c in texte if not unicodedata.combining(c))   # crème -> creme
    return [mot for mot in re.findall(r"[a-z0-9]+", texte) if len(mot) > 1 and mot not in MOTS_VIDES]


class BM25:
    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.frequences = [Counter(tokeniser(doc)) for doc in documents]
        self.longueurs = [sum(f.values()) for f in self.frequences]
        self.longueur_moyenne = sum(self.longueurs) / len(self.longueurs) if self.longueurs else 0.0
        nb_docs_avec: Counter = Counter()
        for frequences in self.frequences:
            nb_docs_avec.update(frequences.keys())
        n = len(documents)
        # IDF : un mot présent partout ne discrimine rien, un mot rare compte beaucoup
        self.idf = {mot: math.log(1 + (n - df + 0.5) / (df + 0.5)) for mot, df in nb_docs_avec.items()}

    def scores(self, requete: str) -> list[float]:
        termes = tokeniser(requete)
        resultats = []
        for frequences, longueur in zip(self.frequences, self.longueurs, strict=True):
            score = 0.0
            norme = 1 - self.b + self.b * longueur / (self.longueur_moyenne or 1)   # pénalise les documents longs
            for terme in termes:
                tf = frequences.get(terme, 0)
                if tf:
                    score += self.idf[terme] * tf * (self.k1 + 1) / (tf + self.k1 * norme)   # tf saturé par k1
            resultats.append(score)
        return resultats
