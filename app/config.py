from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_db_url: str = "postgresql+psycopg://postgres:postgres@localhost:54322/postgres"
    anthropic_api_key: str = ""
    llm_model_name: str = "claude-sonnet-4-5"
    embedding_model_name: str = "BAAI/bge-m3"
    vector_collection_name: str = "tech_trends"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_webhook_secret: str = ""


settings = Settings()
