from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

logger = logging.getLogger(__name__)


def hash_token(raw_token: str) -> str:
    """Returns SHA-256 hex digest of the raw token."""
    return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()


@dataclass
class AppRecord:
    id: str
    name: str
    description: str = ""
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ApiTokenRecord:
    id: str
    app_id: str
    name: str
    key_prefix: str
    key_hash: str
    refresh_token_hash: str
    expires_at: datetime
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


@dataclass
class ApiTokenPair:
    id: str
    app_id: str
    name: str
    api_key: str  # Plaintext, only available at generation time
    refresh_token: str  # Plaintext, only available at generation time
    key_prefix: str
    key_hash: str
    refresh_token_hash: str
    expires_at: datetime


@dataclass
class BotConfigRecord:
    app_id: str
    allowed_chat_ids: list[str] = field(default_factory=list)
    enable_colab_gpu: bool = True
    rate_limit_rpm: int = 60


def generate_api_token_pair(app_id: str, name: str, ttl_days: int = 30) -> ApiTokenPair:
    token_id = str(uuid.uuid4())
    raw_secret = secrets.token_urlsafe(32)
    raw_refresh = secrets.token_urlsafe(32)

    api_key = f"ast_live_{raw_secret}"
    refresh_token = f"ast_ref_{raw_refresh}"
    key_prefix = api_key[:17]  # ast_live_ + 8 characters
    expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)

    return ApiTokenPair(
        id=token_id,
        app_id=app_id,
        name=name,
        api_key=api_key,
        refresh_token=refresh_token,
        key_prefix=key_prefix,
        key_hash=hash_token(api_key),
        refresh_token_hash=hash_token(refresh_token),
        expires_at=expires_at,
    )


class TokenStoreProtocol(Protocol):
    def create_app(self, name: str, description: str = "") -> AppRecord:
        ...

    def list_apps(self) -> list[AppRecord]:
        ...

    def get_app(self, app_id: str) -> AppRecord | None:
        ...

    def create_token(self, app_id: str, name: str, ttl_days: int = 30) -> ApiTokenPair:
        ...

    def list_tokens(self, app_id: str) -> list[ApiTokenRecord]:
        ...

    def validate_api_key(self, raw_api_key: str) -> ApiTokenRecord | None:
        ...

    def refresh_token_pair(self, raw_refresh_token: str) -> ApiTokenPair | None:
        ...

    def revoke_token(self, token_id: str) -> bool:
        ...

    def get_bot_config(self, app_id: str) -> BotConfigRecord:
        ...

    def update_bot_config(
        self,
        app_id: str,
        *,
        allowed_chat_ids: list[str] | None = None,
        enable_colab_gpu: bool | None = None,
        rate_limit_rpm: int | None = None,
    ) -> BotConfigRecord:
        ...

    def get_all_allowed_chat_ids(self) -> set[str]:
        ...

    def is_colab_gpu_enabled(self) -> bool:
        ...


class InMemoryTokenStore:
    def __init__(self) -> None:
        self.apps: dict[str, AppRecord] = {}
        self.tokens: dict[str, ApiTokenRecord] = {}
        self.bot_configs: dict[str, BotConfigRecord] = {}

    def create_app(self, name: str, description: str = "") -> AppRecord:
        app_id = str(uuid.uuid4())
        rec = AppRecord(id=app_id, name=name, description=description)
        self.apps[app_id] = rec
        self.bot_configs[app_id] = BotConfigRecord(app_id=app_id)
        return rec

    def list_apps(self) -> list[AppRecord]:
        return list(self.apps.values())

    def get_app(self, app_id: str) -> AppRecord | None:
        return self.apps.get(app_id)

    def create_token(self, app_id: str, name: str, ttl_days: int = 30) -> ApiTokenPair:
        pair = generate_api_token_pair(app_id=app_id, name=name, ttl_days=ttl_days)
        rec = ApiTokenRecord(
            id=pair.id,
            app_id=app_id,
            name=name,
            key_prefix=pair.key_prefix,
            key_hash=pair.key_hash,
            refresh_token_hash=pair.refresh_token_hash,
            expires_at=pair.expires_at,
        )
        self.tokens[rec.id] = rec
        return pair

    def list_tokens(self, app_id: str) -> list[ApiTokenRecord]:
        return [t for t in self.tokens.values() if t.app_id == app_id and t.is_active and t.revoked_at is None]

    def validate_api_key(self, raw_api_key: str) -> ApiTokenRecord | None:
        cleaned = raw_api_key.strip()
        if not cleaned:
            return None
        target_hash = hash_token(cleaned)
        now = datetime.now(timezone.utc)

        for token in self.tokens.values():
            if token.key_hash == target_hash:
                if not token.is_active or token.revoked_at is not None:
                    return None
                if token.expires_at < now:
                    return None
                token.last_used_at = now
                return token
        return None

    def refresh_token_pair(self, raw_refresh_token: str) -> ApiTokenPair | None:
        cleaned = raw_refresh_token.strip()
        if not cleaned:
            return None
        target_hash = hash_token(cleaned)
        now = datetime.now(timezone.utc)

        old_token = None
        for token in self.tokens.values():
            if token.refresh_token_hash == target_hash:
                if not token.is_active or token.revoked_at is not None:
                    return None
                old_token = token
                break

        if old_token is None:
            return None

        # Revoke old token
        old_token.is_active = False
        old_token.revoked_at = now

        # Retain original validity duration or default 30
        delta_days = (old_token.expires_at - old_token.created_at).days
        ttl_days = delta_days if delta_days > 0 else 30

        new_pair = self.create_token(
            app_id=old_token.app_id,
            name=old_token.name,
            ttl_days=ttl_days,
        )
        return new_pair

    def revoke_token(self, token_id: str) -> bool:
        rec = self.tokens.get(token_id)
        if not rec:
            return False
        rec.is_active = False
        rec.revoked_at = datetime.now(timezone.utc)
        return True

    def get_bot_config(self, app_id: str) -> BotConfigRecord:
        if app_id not in self.bot_configs:
            self.bot_configs[app_id] = BotConfigRecord(app_id=app_id)
        return self.bot_configs[app_id]

    def update_bot_config(
        self,
        app_id: str,
        *,
        allowed_chat_ids: list[str] | None = None,
        enable_colab_gpu: bool | None = None,
        rate_limit_rpm: int | None = None,
    ) -> BotConfigRecord:
        cfg = self.get_bot_config(app_id)
        if allowed_chat_ids is not None:
            cfg.allowed_chat_ids = allowed_chat_ids
        if enable_colab_gpu is not None:
            cfg.enable_colab_gpu = enable_colab_gpu
        if rate_limit_rpm is not None:
            cfg.rate_limit_rpm = rate_limit_rpm
        return cfg

    def get_all_allowed_chat_ids(self) -> set[str]:
        chats: set[str] = set()
        for cfg in self.bot_configs.values():
            for c in cfg.allowed_chat_ids:
                stripped = str(c).strip()
                if stripped:
                    chats.add(stripped)
        return chats

    def is_colab_gpu_enabled(self) -> bool:
        if not self.bot_configs:
            return True
        return any(cfg.enable_colab_gpu for cfg in self.bot_configs.values())


class PostgresTokenStore:
    """PostgreSQL / Supabase persistent token store."""

    def __init__(self, db_url: str) -> None:
        self.db_url = db_url

    def _get_connection(self) -> Any:
        try:
            import psycopg
            # Clean psycopg connection string
            clean_url = self.db_url.replace("postgresql+psycopg://", "postgresql://")
            return psycopg.connect(clean_url)
        except Exception as exc:
            logger.error("Failed to connect to PostgreSQL for TokenStore: %s", exc)
            raise

    def create_app(self, name: str, description: str = "") -> AppRecord:
        app_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO apps (id, name, description, is_active, created_at) VALUES (%s, %s, %s, %s, %s)",
                    (app_id, name, description, True, now),
                )
                cur.execute(
                    "INSERT INTO bot_configs (app_id, allowed_chat_ids, enable_colab_gpu, rate_limit_rpm) VALUES (%s, %s, %s, %s)",
                    (app_id, [], True, 60),
                )
            conn.commit()
        return AppRecord(id=app_id, name=name, description=description, is_active=True, created_at=now)

    def list_apps(self) -> list[AppRecord]:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name, description, is_active, created_at FROM apps ORDER BY created_at DESC")
                rows = cur.fetchall()
        return [
            AppRecord(
                id=str(r[0]),
                name=r[1],
                description=r[2] or "",
                is_active=bool(r[3]),
                created_at=r[4] if isinstance(r[4], datetime) else datetime.now(timezone.utc),
            )
            for r in rows
        ]

    def get_app(self, app_id: str) -> AppRecord | None:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name, description, is_active, created_at FROM apps WHERE id = %s", (app_id,))
                row = cur.fetchone()
        if not row:
            return None
        return AppRecord(
            id=str(row[0]),
            name=row[1],
            description=row[2] or "",
            is_active=bool(row[3]),
            created_at=row[4] if isinstance(row[4], datetime) else datetime.now(timezone.utc),
        )

    def create_token(self, app_id: str, name: str, ttl_days: int = 30) -> ApiTokenPair:
        pair = generate_api_token_pair(app_id=app_id, name=name, ttl_days=ttl_days)
        now = datetime.now(timezone.utc)
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO api_tokens (
                        id, app_id, name, key_prefix, key_hash, refresh_token_hash, expires_at, is_active, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        pair.id,
                        pair.app_id,
                        pair.name,
                        pair.key_prefix,
                        pair.key_hash,
                        pair.refresh_token_hash,
                        pair.expires_at,
                        True,
                        now,
                    ),
                )
            conn.commit()
        return pair

    def list_tokens(self, app_id: str) -> list[ApiTokenRecord]:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, app_id, name, key_prefix, key_hash, refresh_token_hash, expires_at, is_active, created_at, last_used_at, revoked_at
                    FROM api_tokens
                    WHERE app_id = %s AND is_active = TRUE AND revoked_at IS NULL
                    ORDER BY created_at DESC
                    """,
                    (app_id,),
                )
                rows = cur.fetchall()
        return [
            ApiTokenRecord(
                id=str(r[0]),
                app_id=str(r[1]),
                name=r[2],
                key_prefix=r[3],
                key_hash=r[4],
                refresh_token_hash=r[5],
                expires_at=r[6],
                is_active=bool(r[7]),
                created_at=r[8],
                last_used_at=r[9],
                revoked_at=r[10],
            )
            for r in rows
        ]

    def validate_api_key(self, raw_api_key: str) -> ApiTokenRecord | None:
        cleaned = raw_api_key.strip()
        if not cleaned:
            return None
        target_hash = hash_token(cleaned)
        now = datetime.now(timezone.utc)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, app_id, name, key_prefix, key_hash, refresh_token_hash, expires_at, is_active, created_at, last_used_at, revoked_at
                    FROM api_tokens
                    WHERE key_hash = %s AND is_active = TRUE AND revoked_at IS NULL AND expires_at >= %s
                    """,
                    (target_hash, now),
                )
                row = cur.fetchone()
                if not row:
                    return None
                token_id = row[0]
                cur.execute("UPDATE api_tokens SET last_used_at = %s WHERE id = %s", (now, token_id))
            conn.commit()

        return ApiTokenRecord(
            id=str(row[0]),
            app_id=str(row[1]),
            name=row[2],
            key_prefix=row[3],
            key_hash=row[4],
            refresh_token_hash=row[5],
            expires_at=row[6],
            is_active=bool(row[7]),
            created_at=row[8],
            last_used_at=now,
            revoked_at=row[10],
        )

    def refresh_token_pair(self, raw_refresh_token: str) -> ApiTokenPair | None:
        cleaned = raw_refresh_token.strip()
        if not cleaned:
            return None
        target_hash = hash_token(cleaned)
        now = datetime.now(timezone.utc)

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, app_id, name, created_at, expires_at
                    FROM api_tokens
                    WHERE refresh_token_hash = %s AND is_active = TRUE AND revoked_at IS NULL
                    """,
                    (target_hash,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                old_id, app_id, name, created_at, expires_at = row
                cur.execute("UPDATE api_tokens SET is_active = FALSE, revoked_at = %s WHERE id = %s", (now, old_id))
            conn.commit()

        delta_days = (expires_at - created_at).days if (expires_at and created_at) else 30
        ttl_days = delta_days if delta_days > 0 else 30
        return self.create_token(app_id=str(app_id), name=name, ttl_days=ttl_days)

    def revoke_token(self, token_id: str) -> bool:
        now = datetime.now(timezone.utc)
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE api_tokens SET is_active = FALSE, revoked_at = %s WHERE id = %s AND is_active = TRUE",
                    (now, token_id),
                )
                updated = cur.rowcount > 0
            conn.commit()
        return updated

    def get_bot_config(self, app_id: str) -> BotConfigRecord:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT allowed_chat_ids, enable_colab_gpu, rate_limit_rpm FROM bot_configs WHERE app_id = %s",
                    (app_id,),
                )
                row = cur.fetchone()
                if not row:
                    return BotConfigRecord(app_id=app_id)
                return BotConfigRecord(
                    app_id=app_id,
                    allowed_chat_ids=row[0] or [],
                    enable_colab_gpu=bool(row[1]),
                    rate_limit_rpm=int(row[2] or 60),
                )

    def update_bot_config(
        self,
        app_id: str,
        *,
        allowed_chat_ids: list[str] | None = None,
        enable_colab_gpu: bool | None = None,
        rate_limit_rpm: int | None = None,
    ) -> BotConfigRecord:
        current = self.get_bot_config(app_id)
        new_chats = allowed_chat_ids if allowed_chat_ids is not None else current.allowed_chat_ids
        new_gpu = enable_colab_gpu if enable_colab_gpu is not None else current.enable_colab_gpu
        new_rpm = rate_limit_rpm if rate_limit_rpm is not None else current.rate_limit_rpm

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bot_configs (app_id, allowed_chat_ids, enable_colab_gpu, rate_limit_rpm, updated_at)
                    VALUES (%s, %s, %s, %s, now())
                    ON CONFLICT (app_id) DO UPDATE SET
                        allowed_chat_ids = EXCLUDED.allowed_chat_ids,
                        enable_colab_gpu = EXCLUDED.enable_colab_gpu,
                        rate_limit_rpm = EXCLUDED.rate_limit_rpm,
                        updated_at = now()
                    """,
                    (app_id, new_chats, new_gpu, new_rpm),
                )
            conn.commit()
        return BotConfigRecord(
            app_id=app_id,
            allowed_chat_ids=new_chats,
            enable_colab_gpu=new_gpu,
            rate_limit_rpm=new_rpm,
        )

    def get_all_allowed_chat_ids(self) -> set[str]:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT allowed_chat_ids FROM bot_configs")
                rows = cur.fetchall()
        chats: set[str] = set()
        for r in rows:
            for c in (r[0] or []):
                s = str(c).strip()
                if s:
                    chats.add(s)
        return chats

    def is_colab_gpu_enabled(self) -> bool:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT enable_colab_gpu FROM bot_configs")
                rows = cur.fetchall()
        if not rows:
            return True
        return any(bool(r[0]) for r in rows)


class TokenManager:
    """Global manager singleton for token store."""
    _store: TokenStoreProtocol = InMemoryTokenStore()

    @classmethod
    def get_store(cls) -> TokenStoreProtocol:
        return cls._store

    @classmethod
    def set_store(cls, store: TokenStoreProtocol) -> None:
        cls._store = store

    @classmethod
    def reset_store(cls) -> None:
        cls._store = InMemoryTokenStore()
