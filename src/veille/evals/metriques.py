"""Métriques de recherche, écrites à la main (ce sont des définitions à savoir redonner en entretien).

`trouves` = identifiants renvoyés, dans l'ordre ; `pertinents` = identifiants annotés comme pertinents.
"""


def precision_a_k(trouves: list[str], pertinents: set[str], k: int) -> float:
    """Parmi les k premiers résultats, quelle part est pertinente ? (« context precision »)"""
    top = trouves[:k]
    return sum(i in pertinents for i in top) / len(top) if top else 0.0


def rappel_a_k(trouves: list[str], pertinents: set[str], k: int) -> float:
    """Parmi les pertinents, quelle part est dans les k premiers ? (« context recall »)"""
    return sum(i in pertinents for i in trouves[:k]) / len(pertinents) if pertinents else 0.0


def rang_reciproque(trouves: list[str], pertinents: set[str]) -> float:
    """1 / rang du premier pertinent (1 s'il est premier, 0,5 s'il est deuxième…), 0 s'il n'y en a aucun.
    Sa moyenne sur tous les cas est le MRR (Mean Reciprocal Rank)."""
    for rang, identifiant in enumerate(trouves, start=1):
        if identifiant in pertinents:
            return 1 / rang
    return 0.0


def moyenne(valeurs: list[float]) -> float:
    return sum(valeurs) / len(valeurs) if valeurs else 0.0
