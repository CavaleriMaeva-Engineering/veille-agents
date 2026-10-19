import random


def calculer_delai(
    tentative: int, base: float = 1.0, plafond: float = 30.0, jitter: float = 1.0
) -> float:
    delai_non_borne = base * 2 ** (tentative - 1)
    delai_borne = min(delai_non_borne, plafond) + random.uniform(0, jitter)
    return delai_borne
