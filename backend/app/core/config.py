from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str

    enable_auth: bool = True
    api_key_header: str = "X-API-Key"
    api_key: str = "demo-key"

    slack_enabled: bool = False
    slack_webhook_url: Optional[str] = None
    slack_channel_name: Optional[str] = None

settings = Settings()
