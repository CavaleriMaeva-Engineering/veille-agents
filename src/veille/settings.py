from pathlib import Path

import yaml
from pydantic import BaseModel, Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    gemini_api_key: SecretStr


class Marque(BaseModel):
    nom: str
    site: HttpUrl


class Config(BaseModel):
    marche: str
    modele: str
    max_tentatives: int = Field(default=5, ge=1, le=10)
    marques: list[Marque] = Field(min_length=1)


def charger_config(chemin: Path = Path("config/marche.yaml")) -> Config:
    with open(chemin, encoding="utf-8") as f:
        donnees = yaml.safe_load(f)
    return Config.model_validate(donnees)
