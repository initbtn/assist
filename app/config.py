from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_db_url: str = "postgresql+psycopg://postgres:postgres@localhost:54322/postgres"
    anthropic_api_key: str = ""
    embedding_model_name: str = "BAAI/bge-m3"
    vector_collection_name: str = "tech_trends"


settings = Settings()
