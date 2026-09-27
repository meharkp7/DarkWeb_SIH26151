from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AEGIS"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://aegis:aegis@localhost:5432/aegis"
    evidence_storage_path: str = "./artifacts/evidence"

    model_config = SettingsConfigDict(env_prefix="AEGIS_", env_file=".env", extra="ignore")


settings = Settings()
