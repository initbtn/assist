import pytest
from fastapi.testclient import TestClient

from app.auth import InMemoryTokenStore, TokenManager, generate_api_token_pair
from app.firestore_chat import ChatStoreManager, InMemoryChatStore
from app.main import app


@pytest.fixture(autouse=True)
def setup_chat_test_environment(monkeypatch):
    # Setup in-memory token store with a valid B2B test token
    token_store = InMemoryTokenStore()
    app_rec = token_store.create_app(name="initbtn/blog", description="Blog tenant")
    pair = token_store.create_token(app_id=app_rec.id, name="blog-prod")
    monkeypatch.setattr(TokenManager, "get_store", classmethod(lambda cls: token_store))

    # Setup in-memory chat store
    chat_store = InMemoryChatStore()
    monkeypatch.setattr(ChatStoreManager, "get_store", classmethod(lambda cls: chat_store))

    yield {
        "token": pair.api_key,
        "app_id": app_rec.id,
        "chat_store": chat_store,
    }


def test_gateway_chat_unauthorized():
    client = TestClient(app)

    # 1. Missing header
    res = client.post("/v1/gateway/chat/sessions", json={"sessionId": "s1"})
    assert res.status_code == 401

    # 2. Invalid bearer token
    res = client.post(
        "/v1/gateway/chat/sessions",
        headers={"Authorization": "Bearer invalid_token"},
        json={"sessionId": "s1"},
    )
    assert res.status_code == 401


def test_gateway_chat_configured_static_token(monkeypatch):
    from app.config import Settings
    monkeypatch.setattr(Settings, "resolved_gateway_token", lambda self: "ast_live_test_static_gateway_token_123")

    client = TestClient(app)
    headers = {"Authorization": "Bearer ast_live_test_static_gateway_token_123"}
    res = client.post(
        "/v1/gateway/chat/sessions",
        headers=headers,
        json={"sessionId": "s-static", "senderName": "Static", "contact": "", "createdAt": 1, "lastActiveAt": 1, "unreadAdminCount": 0},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True}



def test_post_chat_session_upsert(setup_chat_test_environment):
    client = TestClient(app)
    token = setup_chat_test_environment["token"]
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "sessionId": "sess-001",
        "senderName": "Dominic",
        "contact": "010-1234-5678",
        "createdAt": 1700000000,
        "lastActiveAt": 1700001000,
        "unreadAdminCount": 0,
    }

    res = client.post("/v1/gateway/chat/sessions", headers=headers, json=payload)
    assert res.status_code == 200
    assert res.json() == {"ok": True}

    # Upsert with updated fields
    payload["unreadAdminCount"] = 2
    res2 = client.post("/v1/gateway/chat/sessions", headers=headers, json=payload)
    assert res2.status_code == 200
    assert res2.json() == {"ok": True}


def test_post_chat_message_idempotent(setup_chat_test_environment):
    client = TestClient(app)
    token = setup_chat_test_environment["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Prepare session
    client.post(
        "/v1/gateway/chat/sessions",
        headers=headers,
        json={
            "sessionId": "sess-msg-test",
            "senderName": "User1",
            "contact": "user@example.com",
            "createdAt": 1700000000,
            "lastActiveAt": 1700000000,
            "unreadAdminCount": 0,
        },
    )

    msg_payload = {
        "id": "msg-001",
        "sender": "user",
        "text": "안녕하세요 문의드립니다.",
        "timestamp": 1700000050,
        "timeString": "20:00",
    }

    # First send -> 201 Created
    res1 = client.post(
        "/v1/gateway/chat/sessions/sess-msg-test/messages",
        headers=headers,
        json=msg_payload,
    )
    assert res1.status_code == 201
    assert res1.json() == {"ok": True}

    # Second send with same ID -> 200 OK (idempotent)
    res2 = client.post(
        "/v1/gateway/chat/sessions/sess-msg-test/messages",
        headers=headers,
        json=msg_payload,
    )
    assert res2.status_code == 200
    assert res2.json() == {"ok": True}


def test_get_chat_session_detail_and_ordering(setup_chat_test_environment):
    client = TestClient(app)
    token = setup_chat_test_environment["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 404 when session not found
    res_404 = client.get("/v1/gateway/chat/sessions/non-existent", headers=headers)
    assert res_404.status_code == 404
    assert res_404.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Session not found",
        }
    }

    # Create session
    client.post(
        "/v1/gateway/chat/sessions",
        headers=headers,
        json={
            "sessionId": "sess-order",
            "senderName": "OrderTest",
            "contact": "order@example.com",
            "createdAt": 1700000000,
            "lastActiveAt": 1700003000,
            "unreadAdminCount": 1,
        },
    )

    # Insert messages out of order (timestamp 200, then 100, then 300)
    for m in [
        {"id": "m2", "sender": "admin", "text": "답변 2", "timestamp": 200, "timeString": "10:02"},
        {"id": "m1", "sender": "user", "text": "질문 1", "timestamp": 100, "timeString": "10:01"},
        {"id": "m3", "sender": "user", "text": "추가 3", "timestamp": 300, "timeString": "10:03"},
    ]:
        client.post("/v1/gateway/chat/sessions/sess-order/messages", headers=headers, json=m)

    # Fetch detail
    res = client.get("/v1/gateway/chat/sessions/sess-order", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert data["session"]["sessionId"] == "sess-order"
    assert data["session"]["senderName"] == "OrderTest"
    assert data["session"]["unreadAdminCount"] == 1

    # Messages must be sorted by timestamp ASC
    assert len(data["messages"]) == 3
    assert [m["id"] for m in data["messages"]] == ["m1", "m2", "m3"]
    assert [m["timestamp"] for m in data["messages"]] == [100, 200, 300]


def test_get_chat_sessions_list_ordering_and_limit(setup_chat_test_environment):
    client = TestClient(app)
    token = setup_chat_test_environment["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Insert 3 sessions with different lastActiveAt
    client.post(
        "/v1/gateway/chat/sessions",
        headers=headers,
        json={"sessionId": "s-old", "senderName": "Old", "contact": "", "createdAt": 100, "lastActiveAt": 100, "unreadAdminCount": 0},
    )
    client.post(
        "/v1/gateway/chat/sessions",
        headers=headers,
        json={"sessionId": "s-latest", "senderName": "Latest", "contact": "", "createdAt": 300, "lastActiveAt": 300, "unreadAdminCount": 0},
    )
    client.post(
        "/v1/gateway/chat/sessions",
        headers=headers,
        json={"sessionId": "s-mid", "senderName": "Mid", "contact": "", "createdAt": 200, "lastActiveAt": 200, "unreadAdminCount": 0},
    )

    # List sessions
    res = client.get("/v1/gateway/chat/sessions?limit=50", headers=headers)
    assert res.status_code == 200
    sessions = res.json()["sessions"]

    assert len(sessions) == 3
    # Ordered by lastActiveAt DESC
    assert [s["sessionId"] for s in sessions] == ["s-latest", "s-mid", "s-old"]

    # Test limit=2
    res_limit = client.get("/v1/gateway/chat/sessions?limit=2", headers=headers)
    assert res_limit.status_code == 200
    assert [s["sessionId"] for s in res_limit.json()["sessions"]] == ["s-latest", "s-mid"]


def test_firestore_chat_store_unit_mock():
    from unittest.mock import MagicMock
    from app.firestore_chat import ChatMessage, ChatSessionMeta, FirestoreChatStore

    mock_client = MagicMock()
    mock_coll = MagicMock()
    mock_doc = MagicMock()
    mock_subcoll = MagicMock()
    mock_msg_doc = MagicMock()

    mock_client.collection.return_value = mock_coll
    mock_coll.document.return_value = mock_doc
    mock_doc.collection.return_value = mock_subcoll
    mock_subcoll.document.return_value = mock_msg_doc

    store = FirestoreChatStore(client=mock_client)

    # 1. upsert_session
    sess = ChatSessionMeta(sessionId="s1", senderName="Test", contact="010", createdAt=1, lastActiveAt=2, unreadAdminCount=0)
    store.upsert_session(sess)
    mock_coll.document.assert_called_with("s1")
    mock_doc.set.assert_called_with(sess.to_dict(), merge=True)

    # 2. add_message (new)
    mock_msg_snap = MagicMock()
    mock_msg_snap.exists = False
    mock_msg_doc.get.return_value = mock_msg_snap

    msg = ChatMessage(id="m1", sender="user", text="hi", timestamp=10, timeString="10:00")
    is_new = store.add_message("s1", msg)
    assert is_new is True
    mock_msg_doc.set.assert_called_with(msg.to_dict(), merge=True)

    # 3. add_message (existing -> idempotent)
    mock_msg_snap.exists = True
    is_new_again = store.add_message("s1", msg)
    assert is_new_again is False

    # 4. get_session_with_messages (found)
    mock_doc_snap = MagicMock()
    mock_doc_snap.exists = True
    mock_doc_snap.to_dict.return_value = sess.to_dict()
    mock_doc.get.return_value = mock_doc_snap

    mock_m_doc = MagicMock()
    mock_m_doc.id = "m1"
    mock_m_doc.to_dict.return_value = msg.to_dict()
    mock_subcoll.order_by.return_value.stream.return_value = [mock_m_doc]

    ret_sess, ret_msgs = store.get_session_with_messages("s1")
    assert ret_sess is not None
    assert ret_sess.sessionId == "s1"
    assert len(ret_msgs) == 1
    assert ret_msgs[0].id == "m1"

    # 5. get_session_with_messages (not found)
    mock_doc_snap.exists = False
    none_sess, none_msgs = store.get_session_with_messages("s_none")
    assert none_sess is None
    assert none_msgs == []

