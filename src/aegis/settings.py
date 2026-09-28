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

    model_config = SettingsConfigDict(env_prefix="AEGIS_", env_file=".env", extra="ignore")


settings = Settings()
