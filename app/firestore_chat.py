from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class ChatSessionMeta:
    sessionId: str
    senderName: str
    contact: str = ""
    createdAt: int = 0
    lastActiveAt: int = 0
    unreadAdminCount: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChatMessage:
    id: str
    sender: str  # "admin" | "user"
    text: str
    timestamp: int
    timeString: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChatStoreProtocol(Protocol):
    def upsert_session(self, session: ChatSessionMeta) -> None:
        ...

    def add_message(self, session_id: str, message: ChatMessage) -> bool:
        """Returns True if newly created, False if message ID already existed (idempotent)."""
        ...

    def get_session_with_messages(
        self, session_id: str
    ) -> tuple[ChatSessionMeta | None, list[ChatMessage]]:
        """Returns session meta and messages sorted by timestamp ASC."""
        ...

    def list_sessions(self, limit: int = 50) -> list[ChatSessionMeta]:
        """Returns sessions sorted by lastActiveAt DESC."""
        ...


class InMemoryChatStore:
    def __init__(self) -> None:
        self.sessions: dict[str, ChatSessionMeta] = {}
        self.messages: dict[str, dict[str, ChatMessage]] = {}

    def upsert_session(self, session: ChatSessionMeta) -> None:
        self.sessions[session.sessionId] = session
        if session.sessionId not in self.messages:
            self.messages[session.sessionId] = {}

    def add_message(self, session_id: str, message: ChatMessage) -> bool:
        if session_id not in self.messages:
            self.messages[session_id] = {}
        is_new = message.id not in self.messages[session_id]
        self.messages[session_id][message.id] = message

        # Update lastActiveAt of session if session exists
        if session_id in self.sessions:
            sess = self.sessions[session_id]
            if message.timestamp > sess.lastActiveAt:
                sess.lastActiveAt = message.timestamp

        return is_new

    def get_session_with_messages(
        self, session_id: str
    ) -> tuple[ChatSessionMeta | None, list[ChatMessage]]:
        sess = self.sessions.get(session_id)
        if not sess:
            return None, []
        msgs_map = self.messages.get(session_id, {})
        msgs = sorted(msgs_map.values(), key=lambda m: m.timestamp)
        return sess, msgs

    def list_sessions(self, limit: int = 50) -> list[ChatSessionMeta]:
        sorted_sessions = sorted(
            self.sessions.values(), key=lambda s: s.lastActiveAt, reverse=True
        )
        return sorted_sessions[:limit]


class FirestoreChatStore:
    COLLECTION_NAME = "domlog_chat_sessions"
    SUBCOLLECTION_MESSAGES = "messages"

    def __init__(self, client: Any) -> None:
        self.client = client

    @classmethod
    def from_service_account_info(
        cls, sa_info: dict[str, Any], project_id: str | None = None
    ) -> FirestoreChatStore:
        try:
            from google.cloud import firestore
            from google.oauth2 import service_account

            credentials = service_account.Credentials.from_service_account_info(sa_info)
            client = firestore.Client(
                project=project_id or sa_info.get("project_id"),
                credentials=credentials,
            )
            return cls(client=client)
        except Exception as e:
            logger.error("Failed to initialize FirestoreClient: %s", e)
            raise

    def upsert_session(self, session: ChatSessionMeta) -> None:
        doc_ref = self.client.collection(self.COLLECTION_NAME).document(session.sessionId)
        doc_ref.set(session.to_dict(), merge=True)

    def add_message(self, session_id: str, message: ChatMessage) -> bool:
        session_ref = self.client.collection(self.COLLECTION_NAME).document(session_id)
        msg_ref = session_ref.collection(self.SUBCOLLECTION_MESSAGES).document(message.id)

        snap = msg_ref.get()
        is_new = not snap.exists
        msg_ref.set(message.to_dict(), merge=True)

        # Update lastActiveAt on session
        session_ref.set({"lastActiveAt": message.timestamp}, merge=True)
        return is_new

    def get_session_with_messages(
        self, session_id: str
    ) -> tuple[ChatSessionMeta | None, list[ChatMessage]]:
        session_ref = self.client.collection(self.COLLECTION_NAME).document(session_id)
        snap = session_ref.get()
        if not snap.exists:
            return None, []

        data = snap.to_dict() or {}
        session = ChatSessionMeta(
            sessionId=session_id,
            senderName=data.get("senderName", ""),
            contact=data.get("contact", ""),
            createdAt=data.get("createdAt", 0),
            lastActiveAt=data.get("lastActiveAt", 0),
            unreadAdminCount=data.get("unreadAdminCount", 0),
        )

        from google.cloud import firestore

        query = session_ref.collection(self.SUBCOLLECTION_MESSAGES).order_by(
            "timestamp", direction=firestore.Query.ASCENDING
        )
        messages: list[ChatMessage] = []
        for doc in query.stream():
            m_data = doc.to_dict() or {}
            messages.append(
                ChatMessage(
                    id=doc.id,
                    sender=m_data.get("sender", "user"),
                    text=m_data.get("text", ""),
                    timestamp=m_data.get("timestamp", 0),
                    timeString=m_data.get("timeString", ""),
                )
            )

        return session, messages

    def list_sessions(self, limit: int = 50) -> list[ChatSessionMeta]:
        from google.cloud import firestore

        query = (
            self.client.collection(self.COLLECTION_NAME)
            .order_by("lastActiveAt", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        sessions: list[ChatSessionMeta] = []
        for doc in query.stream():
            data = doc.to_dict() or {}
            sessions.append(
                ChatSessionMeta(
                    sessionId=doc.id,
                    senderName=data.get("senderName", ""),
                    contact=data.get("contact", ""),
                    createdAt=data.get("createdAt", 0),
                    lastActiveAt=data.get("lastActiveAt", 0),
                    unreadAdminCount=data.get("unreadAdminCount", 0),
                )
            )
        return sessions


class ChatStoreManager:
    _instance: ChatStoreProtocol | None = None

    @classmethod
    def get_store(cls) -> ChatStoreProtocol:
        if cls._instance is not None:
            return cls._instance

        settings = Settings()
        sa_json_str = settings.resolved_firestore_sa_key_json()
        if sa_json_str:
            try:
                sa_info = json.loads(sa_json_str)
                cls._instance = FirestoreChatStore.from_service_account_info(
                    sa_info, project_id=settings.firebase_project_id
                )
                logger.info("Initialized FirestoreChatStore successfully")
                return cls._instance
            except Exception as e:
                logger.error("Failed to build FirestoreChatStore from SA key: %s", e)

        logger.warning("Using InMemoryChatStore fallback (no valid Firestore SA key configured)")
        cls._instance = InMemoryChatStore()
        return cls._instance

    @classmethod
    def set_store(cls, store: ChatStoreProtocol | None) -> None:
        cls._instance = store
