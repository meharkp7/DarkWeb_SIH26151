from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AEGIS"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://aegis:aegis@localhost:5432/aegis"
    evidence_storage_path: str = "./artifacts/evidence"
    # Comma-separated trusted browser origins. Keep empty by default: the
    # Vite development proxy is same-origin and production must opt in.
    cors_origins: str = ""

    model_config = SettingsConfigDict(env_prefix="AEGIS_", env_file=".env", extra="ignore")


settings = Settings()
