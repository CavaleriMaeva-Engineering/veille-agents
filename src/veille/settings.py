from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    groq_api_key: SecretStr
    apify_token: SecretStr
    slack_webhook_url: SecretStr | None = None
    veille_api_key: SecretStr | None = None   # clé exigée par l'API (en-tête X-API-Key) ; absente = API fermée


class Marque(BaseModel):
    nom: str
    site: HttpUrl


class ReglageLLM(BaseModel):
    """Modèle et effort de raisonnement d'une étape. None = valeur par défaut (modele de la config, effort du modèle)."""
    modele: str | None = None
    effort: Literal["low", "medium", "high"] | None = None


class Config(BaseModel):
    marche: str
    modele: str
    # Juge des évals : un AUTRE modèle que celui qui travaille (pas d'auto-préférence), plus gros, et avec son
    # propre quota Groq (les limites sont par modèle).
    modele_juge: str = "openai/gpt-oss-120b"
    max_tentatives: int = Field(default=5, ge=1, le=10)
    marques: list[Marque] = Field(min_length=1)
    outils_actifs: list[str] = Field(
        default=["lire_page_web", "chercher_pubs_meta", "chercher_pubs_tiktok"], min_length=1
    )
    # PJ15 : routage par étape. Une étape simple (choisir des outils) n'a pas besoin du même modèle ni du même
    # effort de raisonnement qu'une étape difficile. Les étapes absentes prennent `modele`.
    etapes: dict[str, ReglageLLM] = Field(default_factory=dict)

    def reglage(self, etape: str) -> tuple[str, str | None]:
        reglage = self.etapes.get(etape, ReglageLLM())
        return reglage.modele or self.modele, reglage.effort

def charger_config(chemin: Path = Path("config/marche.yaml")) -> Config:
    with open(chemin, encoding="utf-8") as f:
        donnees = yaml.safe_load(f)
    return Config.model_validate(donnees)
