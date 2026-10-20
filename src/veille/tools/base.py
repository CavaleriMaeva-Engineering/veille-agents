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
