from typing import Any

from fastapi import APIRouter, Depends

from app.auth import ApiTokenRecord, verify_api_key
from app.config import settings

router = APIRouter()


@router.get("/v1/chat/models")
def list_chat_models(token: ApiTokenRecord = Depends(verify_api_key)) -> dict[str, Any]:
    return {
        "models": [settings.llm_model_name, settings.ollama_model_name],
        "authenticated_app_id": token.app_id,
    }
