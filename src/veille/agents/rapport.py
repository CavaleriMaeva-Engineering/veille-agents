import json
from typing import Literal

import groq
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from veille.llm.client import appeler_llm
from veille.tools.registre import resumer_erreurs


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
        description="La pub qui tourne depuis le plus longtemps et sa durée en jours. "
        "Valeur JSON null (pas le texte \"null\") si les données ne permettent pas de le dire."
    )
    donnees_manquantes: list[str] = Field(
        description="Les sources ou informations qu'on n'a PAS pu obtenir (ex. : TikTok indisponible). Pas de critique de la stratégie."
    )

    @field_validator("pub_la_plus_durable")
    @classmethod
    def texte_vide_vers_none(cls, valeur: str | None) -> str | None:
        if valeur is not None and valeur.strip().lower() in {"", "null", "none", "inconnue"}:
            return None
        return valeur


def format_json_strict(modele: type[BaseModel]) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {"name": modele.__name__, "strict": True, "schema": modele.model_json_schema()},
    }


PROMPT_REDACTION = """Tu rédiges un rapport de veille publicitaire à partir de données collectées.
Règles :
- Utilise UNIQUEMENT les données fournies. N'invente rien, n'interprète pas la stratégie.
- Chaque constat indique sa source : meta, tiktok ou site.
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
    execution_id: str,
    max_essais: int = 2,
) -> RapportVeille:
    messages = [
        {"role": "system", "content": PROMPT_REDACTION},
        {"role": "user", "content": f"Marque : {marque}\n\nDonnées collectées :\n" + json.dumps(observations, ensure_ascii=False)},
    ]
    for essai in range(1, max_essais + 1):
        reponse = appeler_llm(
            client, modele, messages, agent="redacteur", execution_id=execution_id,
            format_reponse=format_json_strict(RapportVeille),
            max_tokens_sortie=4096,
            effort_raisonnement="low",
        )
        try:
            return RapportVeille.model_validate_json(reponse.texte or "")
        except ValidationError as erreur:
            if essai == max_essais:
                raise
            messages.append({"role": "assistant", "content": reponse.texte or ""})
            messages.append({"role": "user", "content": f"Ton JSON ne respecte pas le format : {resumer_erreurs(erreur)}. Corrige-le."})