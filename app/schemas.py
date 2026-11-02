from typing import Any
from pydantic import BaseModel, Field

from app.articles import ModelBriefComparison


class TargetStatusPatch(BaseModel):
    is_active: bool


class IngestRequest(BaseModel):
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunk_size: int = 1000
    chunk_overlap: int = 200


class IngestResponse(BaseModel):
    ingested_chunks: int
    skipped_duplicate: bool


class QueryRequest(BaseModel):
    question: str
    domain: str | None = None
    target_name: str | None = None
    k: int = 4


class CollectRequest(BaseModel):
    domain: str | None = None
    include_seed: bool = False
    per_target_limit: int = 3


class BriefSendRequest(BaseModel):
    chat_id: str | None = None
    domain: str | None = None
    date_str: str | None = None


class BriefSendResponse(BaseModel):
    sent: bool
    chat_id: str
    brief: str
    article_slug: str
    article_url: str
    summary_lines: list[str]


class BriefCompareRequest(BaseModel):
    models: list[str] = Field(default_factory=lambda: ["A", "C"])
    domain: str | None = None
    date_str: str | None = None


class BriefCompareResponse(BaseModel):
    date: str
    comparisons: dict[str, ModelBriefComparison]


class AppCreateRequest(BaseModel):
    name: str
    description: str = ""


class TokenCreateRequest(BaseModel):
    name: str
    ttl_days: int = 30


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class BotConfigUpdateRequest(BaseModel):
    allowed_chat_ids: list[str] | None = None
    enable_colab_gpu: bool | None = None
    rate_limit_rpm: int | None = None
