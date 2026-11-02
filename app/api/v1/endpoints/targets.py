from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_target_store
from app.schemas import TargetStatusPatch
from app.targets import InMemoryTargetStore, ResearchTarget, ResearchTargetCreate

router = APIRouter()


@router.get("/targets", response_model=list[ResearchTarget])
def list_targets(
    domain: str | None = Query(default=None),
    active_only: bool = Query(default=True),
    t_store: InMemoryTargetStore = Depends(get_target_store),
) -> list[ResearchTarget]:
    return t_store.list_targets(domain=domain, active_only=active_only)


@router.post(
    "/targets",
    response_model=ResearchTarget,
    status_code=status.HTTP_201_CREATED,
)
def create_target(
    payload: ResearchTargetCreate,
    t_store: InMemoryTargetStore = Depends(get_target_store),
) -> ResearchTarget:
    try:
        return t_store.add_target(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.patch("/targets/{target_id}", response_model=ResearchTarget)
def patch_target(
    target_id: str,
    payload: TargetStatusPatch,
    t_store: InMemoryTargetStore = Depends(get_target_store),
) -> ResearchTarget:
    try:
        return t_store.set_active(target_id, is_active=payload.is_active)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
