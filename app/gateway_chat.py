from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import ApiTokenRecord, verify_api_key
from app.firestore_chat import ChatMessage, ChatSessionMeta, ChatStoreManager

logger = logging.getLogger(__name__)

router = APIRouter()


class SessionMetaPayload(BaseModel):
    sessionId: str = Field(..., min_length=1)
    senderName: str = Field(..., min_length=1)
    contact: str = ""
    createdAt: int = 0
    lastActiveAt: int = 0
    unreadAdminCount: int = 0
    telegramTopicId: int | None = None


class MessagePayload(BaseModel):
    id: str = Field(..., min_length=1)
    sender: Literal["admin", "user"]
    text: str = Field(..., min_length=1)
    timestamp: int = 0
    timeString: str = ""


@router.post("/sessions", status_code=status.HTTP_200_OK)
def upsert_chat_session(
    payload: SessionMetaPayload,
    token: ApiTokenRecord = Depends(verify_api_key),
) -> dict[str, bool]:
    store = ChatStoreManager.get_store()
    meta = ChatSessionMeta(
        sessionId=payload.sessionId,
        senderName=payload.senderName,
        contact=payload.contact,
        createdAt=payload.createdAt,
        lastActiveAt=payload.lastActiveAt,
        unreadAdminCount=payload.unreadAdminCount,
        telegramTopicId=payload.telegramTopicId,
    )
    store.upsert_session(meta)
    return {"ok": True}


@router.post("/sessions/{sessionId}/messages")
def add_chat_message(
    sessionId: str,
    payload: MessagePayload,
    response: Response,
    token: ApiTokenRecord = Depends(verify_api_key),
) -> dict[str, bool]:
    store = ChatStoreManager.get_store()
    msg = ChatMessage(
        id=payload.id,
        sender=payload.sender,
        text=payload.text,
        timestamp=payload.timestamp,
        timeString=payload.timeString,
    )
    is_new = store.add_message(session_id=sessionId, message=msg)
    if is_new:
        response.status_code = status.HTTP_201_CREATED
    else:
        response.status_code = status.HTTP_200_OK
    return {"ok": True}


@router.get("/sessions/{sessionId}")
def get_chat_session(
    sessionId: str,
    token: ApiTokenRecord = Depends(verify_api_key),
) -> dict[str, Any]:
    store = ChatStoreManager.get_store()
    session, messages = store.get_session_with_messages(sessionId)
    if not session:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": {"code": "NOT_FOUND", "message": "Session not found"}},
        )
    return {
        "session": session.to_dict(),
        "messages": [m.to_dict() for m in messages],
    }


@router.get("/sessions")
def list_chat_sessions(
    limit: int = Query(default=50, ge=1, le=100),
    token: ApiTokenRecord = Depends(verify_api_key),
) -> dict[str, list[dict[str, Any]]]:
    store = ChatStoreManager.get_store()
    sessions = store.list_sessions(limit=limit)
    return {"sessions": [s.to_dict() for s in sessions]}
