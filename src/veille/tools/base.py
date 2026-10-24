from urllib.parse import urlparse

from pydantic import BaseModel

from veille.traces import noter


def decrire_outil(nom: str, description: str, args: type[BaseModel]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": nom,
            "description": description,
            "parameters": args.model_json_schema(),
        },
    }


def est_du_domaine(url: str | None, domaine: str) -> bool:
    if not url:
        return False
    hote = (urlparse(url).hostname or "").removeprefix("www.")
    return hote == domaine or hote.endswith("." + domaine)


def noter_cout_apify(execution) -> None:
    """Ajoute au span de l'outil le coût du run Apify (champ usageTotalUsd de l'API), s'il est connu."""
    cout = getattr(execution, "usage_total_usd", None)
    noter(cout_apify_usd=cout if isinstance(cout, (int, float)) else None)
