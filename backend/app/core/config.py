from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str

    enable_auth: bool = True
    api_key_header: str = "X-API-Key"
    api_key: str = "demo-key"

settings = Settings()
