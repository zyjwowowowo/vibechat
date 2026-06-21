from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "VibeChat API"
    environment: str = "development"
    database_url: str = "sqlite:///./vibechat.db"
    cors_origins: str = "http://localhost:3000"
    llm_provider: str = "openai"
    openai_base_url: str = ""
    openai_api_key: str = ""
    openai_model: str = "deepseekpro"
    anthropic_base_url: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = "deepseekpro"
    llm_timeout_seconds: float = 25
    llm_mock_mode: bool = False
    match_timeout_seconds: int = 10

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

