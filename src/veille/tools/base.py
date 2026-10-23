from urllib.parse import urlparse

from pydantic import BaseModel


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
