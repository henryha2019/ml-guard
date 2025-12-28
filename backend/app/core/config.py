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

    # -----------------------------
    # AWS Cost Explorer 
    # -----------------------------
    # If aws_profile is set, boto3.Session(profile_name=...) is used.
    aws_profile: Optional[str] = None

    # Cost Explorer endpoint is in us-east-1. :contentReference[oaicite:2]{index=2}
    aws_ce_region: str = "us-east-1"

    # Cost metric returned by Cost Explorer (commonly UnblendedCost).
    aws_ce_cost_metric: str = "UnblendedCost"


settings = Settings()
