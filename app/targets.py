from datetime import datetime, timezone
import hashlib
from typing import Any, Protocol
import uuid

from pydantic import BaseModel, Field


class ResearchTargetCreate(BaseModel):
    domain: str
    name: str
    source_type: str
    source_config: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class ResearchTarget(ResearchTargetCreate):
    id: str
    last_collected_at: datetime | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


DEFAULT_SEED_TARGETS: tuple[ResearchTargetCreate, ...] = (
    ResearchTargetCreate(
        domain="ai_agent_llm",
        name="Claude Code",
        source_type="github_repo",
        source_config={"repo": "anthropics/claude-code", "track": ["releases"]},
    ),
    ResearchTargetCreate(
        domain="ai_agent_llm",
        name="LangChain",
        source_type="github_repo",
        source_config={"repo": "langchain-ai/langchain", "track": ["releases"]},
    ),
    ResearchTargetCreate(
        domain="fullstack_web",
        name="Next.js",
        source_type="github_repo",
        source_config={"repo": "vercel/next.js", "track": ["releases", "discussions"]},
    ),
    ResearchTargetCreate(
        domain="fullstack_web",
        name="NestJS",
        source_type="github_repo",
        source_config={"repo": "nestjs/nest", "track": ["releases"]},
    ),
    ResearchTargetCreate(
        domain="fullstack_web",
        name="React",
        source_type="github_repo",
        source_config={"repo": "facebook/react", "track": ["releases"]},
    ),
    ResearchTargetCreate(
        domain="infra_devops",
        name="Terraform",
        source_type="github_repo",
        source_config={"repo": "hashicorp/terraform", "track": ["releases"]},
    ),
    ResearchTargetCreate(
        domain="infra_devops",
        name="Kubernetes",
        source_type="github_repo",
        source_config={"repo": "kubernetes/kubernetes", "track": ["releases"]},
    ),
)


class InMemoryTargetStore:
    def __init__(self, *, seed: bool = True) -> None:
        self._targets: dict[str, ResearchTarget] = {}
        if seed:
            for item in DEFAULT_SEED_TARGETS:
                self.add_target(item)

    def list_targets(
        self,
        *,
        domain: str | None = None,
        active_only: bool = True,
    ) -> list[ResearchTarget]:
        items = list(self._targets.values())
        if active_only:
            items = [t for t in items if t.is_active]
        if domain:
            items = [t for t in items if t.domain == domain]
        return items

    def add_target(self, payload: ResearchTargetCreate) -> ResearchTarget:
        key = (payload.domain, payload.name, payload.source_type)
        for existing in self._targets.values():
            if (existing.domain, existing.name, existing.source_type) == key:
                raise ValueError(f"Target already exists: {key}")

        target = ResearchTarget(
            id=str(uuid.uuid4()),
            **payload.model_dump(),
        )
        self._targets[target.id] = target
        return target

    def set_active(self, target_id: str, *, is_active: bool) -> ResearchTarget:
        if target_id not in self._targets:
            raise KeyError(f"Target not found: {target_id}")
        updated = self._targets[target_id].model_copy(
            update={"is_active": is_active}
        )
        self._targets[target_id] = updated
        return updated


def compute_content_hash(text: str) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        raise ValueError("Cannot hash empty text")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class DeduplicationStoreProtocol(Protocol):
    def is_duplicate(self, source_url: str, content_hash: str) -> bool: ...

    def record(
        self,
        *,
        source_url: str,
        content_hash: str,
        domain: str = "",
        target_name: str = "",
    ) -> None: ...


class InMemoryDeduplicationStore:
    def __init__(self) -> None:
        self._records: dict[str, str] = {}

    def is_duplicate(self, source_url: str, content_hash: str) -> bool:
        return self._records.get(source_url) == content_hash

    def record(
        self,
        *,
        source_url: str,
        content_hash: str,
        domain: str = "",
        target_name: str = "",
    ) -> None:
        self._records[source_url] = content_hash
