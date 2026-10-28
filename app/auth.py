from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol


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

    if ttl_days >= 0:
        expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)
    else:
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

        # Generate new token pair for the same app and name
        new_pair = self.create_token(
            app_id=old_token.app_id,
            name=old_token.name,
            ttl_days=30,
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


class TokenManager:
    """Global manager singleton for token store."""
    _store: TokenStoreProtocol = InMemoryTokenStore()

    @classmethod
    def get_store(cls) -> TokenStoreProtocol:
        return cls._store

    @classmethod
    def set_store(cls, store: TokenStoreProtocol) -> None:
        cls._store = store
