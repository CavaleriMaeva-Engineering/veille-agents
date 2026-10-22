from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Constat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    affirmation: str = Field(description="Un fait observé, en une phrase, sans identifiant technique.")
    source: Literal["meta", "tiktok", "site"] = Field(description="D'où vient ce fait.")


class RapportVeille(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marque: str
    produits_pousses: list[Constat]
    messages_et_promesses: list[Constat]
    offres: list[Constat]
    formats_et_plateformes: list[Constat]
    cible: list[Constat]
    pub_la_plus_durable: str | None = Field(
        description="La pub qui tourne depuis le plus longtemps et sa durée, ou null si inconnue."
    )
    donnees_manquantes: list[str] = Field(
        description="Les sources ou informations qu'on n'a PAS pu obtenir (ex. : TikTok indisponible). Pas de critique de la stratégie."
    )


def format_json_strict(modele: type[BaseModel]) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {"name": modele.__name__, "strict": True, "schema": modele.model_json_schema()},
    }