from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    gemini_api_key : SecretStr