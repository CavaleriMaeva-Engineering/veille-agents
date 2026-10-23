import json
from typing import Literal

import groq
from pydantic import BaseModel, ConfigDict, Field

from veille.agents.signaux import Signaux
from veille.llm.structure import generer_structure


class Constat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    affirmation: str = Field(description="Un fait observé, en une phrase, sans identifiant technique.")
    sources: list[Literal["meta", "tiktok", "site"]] = Field(
        description="Toutes les sources qui confirment ce fait (une ou plusieurs). Un fait vu sur plusieurs sources = UN seul constat."
    )


class RapportVeille(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marque: str
    produits_pousses: list[Constat]
    messages_et_promesses: list[Constat]
    offres: list[Constat]
    formats_et_plateformes: list[Constat]
    cible: list[Constat]
    donnees_manquantes: list[str] = Field(
        description="Les sources ou informations qu'on n'a PAS pu obtenir (ex. : TikTok indisponible). Pas de critique de la stratégie."
    )


PROMPT_REDACTION = """Tu rédiges un rapport de veille publicitaire à partir de données collectées.

Règles de fond :
- Utilise UNIQUEMENT les données fournies. N'invente rien, n'interprète pas la stratégie.
- Les signaux calculés sont exacts : utilise-les pour les chiffres (nombre de pubs, formats, durées), ne recalcule rien.

Règles de couverture (sois exhaustif) :
- produits_pousses : UN constat par produit distinct présent dans les pubs, avec sa durée de diffusion si elle est connue.
- Mentionne la pub la plus durable (signaux) et sa durée en jours : c'est la pub la plus probablement rentable.
- offres : chaque élément commercial présent dans les données (prix, valeur annoncée, cadeau, seuil de livraison gratuite, édition limitée).

Règles de forme :
- Chaque constat liste TOUTES ses sources (meta, tiktok, site). Un même fait vu sur plusieurs sources = un seul constat, jamais de doublon.
- Ne mélange pas dans un même constat des faits de sources différentes s'ils ne disent pas la même chose.
- Pas d'identifiant technique (numéros de pub, paramètres d'URL).
- Si une source a renvoyé une erreur, mentionne-la dans donnees_manquantes.
- Une liste vide est acceptable si les données ne disent rien sur ce point."""


def extraire_observations(messages: list[dict]) -> list[str]:
    return [m["content"] for m in messages if m["role"] == "tool"]


def rediger_rapport(
    client: groq.Groq,
    modele: str,
    marque: str,
    observations: list[str],
    signaux: Signaux,
    execution_id: str,
    max_essais: int = 2,
) -> RapportVeille:
    messages = [
        {"role": "system", "content": PROMPT_REDACTION},
        {
            "role": "user",
            "content": (
                f"Marque : {marque}\n\n"
                f"Signaux calculés (exacts) :\n{signaux.model_dump_json()}\n\n"
                f"Données collectées :\n{json.dumps(observations, ensure_ascii=False)}"
            ),
        },
    ]
    return generer_structure(
        client, modele, messages, RapportVeille, agent="redacteur", execution_id=execution_id, max_essais=max_essais
    )