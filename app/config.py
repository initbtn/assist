import ipaddress
import subprocess
from typing import Callable

from pydantic_settings import BaseSettings, SettingsConfigDict

TELEGRAM_WEBHOOK_CIDRS: tuple[str, ...] = (
    "149.154.160.0/20",
    "91.108.4.0/22",
)


def build_gcp_allowed_source_ranges(
    admin_ip: str,
    *,
    include_telegram_webhooks: bool = True,
) -> str:
    cleaned = (admin_ip or "").strip()
    if not cleaned:
        raise ValueError("admin_ip must not be empty")
    try:
        net = ipaddress.IPv4Network(cleaned, strict=False)
    except Exception as exc:
        raise ValueError(f"Invalid admin_ip '{cleaned}'") from exc
    if net.prefixlen == 0:
        raise ValueError("0.0.0.0/0 is not permitted for restricted GCP firewall")

    ranges = [str(net)]
    if include_telegram_webhooks:
        ranges.extend(TELEGRAM_WEBHOOK_CIDRS)
    return ",".join(ranges)


def _default_pass_runner(key_path: str) -> str:
    proc = subprocess.run(
        ["pass", "show", key_path],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc.stdout


def resolve_pass_secret(
    key_path: str,
    *,
    runner: Callable[[str], str] | None = None,
) -> str:
    cleaned_key = key_path.strip()
    if not cleaned_key:
        raise ValueError("key_path must not be empty")
    try:
        active_runner = runner if runner is not None else _default_pass_runner
        raw = active_runner(cleaned_key)
    except Exception:
        return ""
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_db_url: str = "postgresql+psycopg://postgres:postgres@localhost:54322/postgres"
    use_pgvector: bool = False
    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model_name: str = "gemma3:12b"
    anthropic_api_key: str = ""
    llm_model_name: str = "claude-sonnet-4-5"
    embedding_model_name: str = "Snowflake/snowflake-arctic-embed-l-v2.0"
    vector_collection_name: str = "tech_trends"
    github_token: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    ops_telegram_bot_token: str = ""
    ops_telegram_chat_id: str = ""
    telegram_webhook_secret: str = ""
    public_ui_base_url: str = "https://assist-brief.vercel.app"

    def resolved_github_token(self) -> str:
        if self.github_token.strip():
            return self.github_token.strip()
        return resolve_pass_secret("github/gh-token")

    def resolved_telegram_bot_token(self) -> str:
        if self.telegram_bot_token.strip():
            return self.telegram_bot_token.strip()
        return resolve_pass_secret("telegram/domAssistBot/bot-token")

    def resolved_telegram_chat_id(self) -> str:
        if self.telegram_chat_id.strip():
            return self.telegram_chat_id.strip()
        return resolve_pass_secret("telegram/domAssistBot/chat-id")

    def resolved_ops_telegram_bot_token(self) -> str:
        if self.ops_telegram_bot_token.strip():
            return self.ops_telegram_bot_token.strip()
        return resolve_pass_secret("telegram/bot-token")

    def resolved_ops_telegram_chat_id(self) -> str:
        if self.ops_telegram_chat_id.strip():
            return self.ops_telegram_chat_id.strip()
        return resolve_pass_secret("telegram/chat-id")


settings = Settings()
