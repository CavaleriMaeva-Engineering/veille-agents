import random
import time

import groq
import httpx


def calculer_delai(
    tentative: int, base: float = 1.0, plafond: float = 30.0, jitter: float = 1.0
) -> float:
    delai_non_borne = base * 2 ** (tentative - 1)
    delai_borne = min(delai_non_borne, plafond) + random.uniform(0, jitter)
    return delai_borne


def code_est_passager(code: int) -> bool:
    return code == 429 or 500 <= code <= 599


def erreur_est_passagere(erreur: Exception) -> bool:
    if isinstance(erreur, groq.APIConnectionError):
        return True
    elif isinstance(erreur, groq.APIStatusError):
        return code_est_passager(erreur.status_code)
    elif isinstance(erreur, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    elif isinstance(erreur, httpx.HTTPStatusError):
        return code_est_passager(erreur.response.status_code)
    return False


def delai_impose(erreur: Exception) -> float | None:
    reponse = getattr(erreur, "response", None)
    if reponse is None:
        return None
    valeur = reponse.headers.get("retry-after")
    try:
        return float(valeur) if valeur is not None else None
    except ValueError:
        return None


def appeler_avec_tentatives(appel, max_tentatives: int = 5, attendre=time.sleep, attente_max: float = 60.0):
    for tentative in range(1, max_tentatives + 1):
        try:
            return appel()
        except Exception as erreur:
            if not erreur_est_passagere(erreur) or tentative == max_tentatives:
                raise
            delai = delai_impose(erreur)
            if delai is None:
                delai = calculer_delai(tentative)
            elif delai > attente_max:
                raise
            attendre(delai)