from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    github_app_id: str
    github_app_slug: str
    github_private_key: str
    github_webhook_secret: str

    gemini_api_key: str
    groq_api_key: str

    dodo_payments_api_key: str = ""
    dodo_webhook_secret: str = ""
    dodo_checkout_url: str = ""

    app_url: str = "https://autopr-reviewer.onrender.com"
    database_url: str = "sqlite:///./autopr.db"

    model_config = SettingsConfigDict(env_file=".env")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
