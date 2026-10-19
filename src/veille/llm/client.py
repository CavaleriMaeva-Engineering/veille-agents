import random
import groq


def calculer_delai(
    tentative: int, base: float = 1.0, plafond: float = 30.0, jitter: float = 1.0
) -> float:
    delai_non_borne = base * 2 ** (tentative - 1)
    delai_borne = min(delai_non_borne, plafond) + random.uniform(0, jitter)
    return delai_borne

def code_est_passager(code: int) -> bool:
    return code == 429 or 500 <= code <= 599 

def erreur_est_passagere(erreur: Exception) -> bool:
    if isinstance(erreur, groq.APIConnectionError) :
        return True
    elif isinstance(erreur, groq.APIStatusError) :
        return code_est_passager(erreur.status_code)
    return False