from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AEGIS"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://aegis:aegis@localhost:5432/aegis"
    evidence_storage_path: str = "./artifacts/evidence"
    # Comma-separated trusted browser origins. Keep empty by default: the
    # Vite development proxy is same-origin and production must opt in.
    cors_origins: str = ""
    opensearch_url: str = "http://localhost:9200"
    opensearch_index_prefix: str = "aegis"
    opensearch_username: str | None = None
    opensearch_password: str | None = None
    api_key: str | None = None
    enable_api_key_auth: bool = False
    auth_email: str = "analyst@aegis.intel"
    auth_password: str = "ChangeMe-AEGIS"
    auth_secret: str = "dev-only-change-this-secret"
    auth_session_ttl_s: int = 28800
    auth_display_name: str = "Mehar Kapoor"
    auth_role: str = "Senior Intelligence Analyst"
    auth_organization: str = "AEGIS Intelligence Group"

    model_config = SettingsConfigDict(env_prefix="AEGIS_", env_file=".env", extra="ignore")


settings = Settings()
