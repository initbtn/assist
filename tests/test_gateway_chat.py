import pytest
from fastapi.testclient import TestClient

from app.auth import InMemoryTokenStore, TokenManager, generate_api_token_pair
from app.firestore_chat import ChatStoreManager, InMemoryChatStore
from app.main import app


@pytest.fixture(autouse=True)
def setup_chat_test_environment(monkeypatch):
    from app.security import fetch_raw_gateway_credentials
    if hasattr(fetch_raw_gateway_credentials, "cache_clear"):
        fetch_raw_gateway_credentials.cache_clear()

    # Setup in-memory token store with a valid B2B test token
    token_store = InMemoryTokenStore()
    app_rec = token_store.create_app(name="initbtn/blog", description="Blog tenant")
    pair = token_store.create_token(app_id=app_rec.id, name="blog-prod")
    monkeypatch.setattr(TokenManager, "get_store", classmethod(lambda cls: token_store))

    # Setup in-memory chat store
    chat_store = InMemoryChatStore()
    ChatStoreManager.set_store(chat_store)

    yield {
        "token": pair.api_key,
        "app_id": app_rec.id,
        "chat_store": chat_store,
    }

    ChatStoreManager.set_store(None)
    if hasattr(fetch_raw_gateway_credentials, "cache_clear"):
        fetch_raw_gateway_credentials.cache_clear()


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


def test_firestore_chat_store_last_active_conditional_update():
    from unittest.mock import MagicMock
    from app.firestore_chat import ChatMessage, FirestoreChatStore

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

    # Mock session currently has lastActiveAt = 500
    mock_session_snap = MagicMock()
    mock_session_snap.exists = True
    mock_session_snap.to_dict.return_value = {"lastActiveAt": 500}
    mock_doc.get.return_value = mock_session_snap

    # 1. Incoming newer message (timestamp 600 > 500) -> should update lastActiveAt
    msg_new = ChatMessage(id="m_new", sender="user", text="newer", timestamp=600, timeString="")
    store.add_message("s1", msg_new)
    mock_doc.set.assert_called_with({"lastActiveAt": 600}, merge=True)

    # Reset mock call
    mock_doc.set.reset_mock()

    # 2. Incoming older message (timestamp 400 < 500) -> should NOT update lastActiveAt
    msg_old = ChatMessage(id="m_old", sender="user", text="older", timestamp=400, timeString="")
    store.add_message("s1", msg_old)
    mock_doc.set.assert_not_called()


def test_fetch_raw_gateway_credentials_from_secret_manager(monkeypatch):
    import json
    from unittest.mock import MagicMock
    from app.security import fetch_raw_gateway_credentials

    if hasattr(fetch_raw_gateway_credentials, "cache_clear"):
        fetch_raw_gateway_credentials.cache_clear()

    # Clear env
    monkeypatch.delenv("GATEWAY_TOKEN", raising=False)
    monkeypatch.delenv("FIRESTORE_SA_KEY_JSON", raising=False)
    monkeypatch.setenv("GCP_PROJECT", "initbtn-510706")

    mock_payload = {
        "gateway_token": "ast_live_from_sm_123",
        "firestore_sa_key": {"type": "service_account", "project_id": "waffle-dominic"},
    }

    mock_sm_client = MagicMock()
    mock_response = MagicMock()
    mock_response.payload.data = json.dumps(mock_payload).encode("utf-8")
    mock_sm_client.access_secret_version.return_value = mock_response

    mock_sm_module = MagicMock()
    mock_sm_module.SecretManagerServiceClient.return_value = mock_sm_client

    import sys
    monkeypatch.setitem(sys.modules, "google.cloud.secretmanager", mock_sm_module)

    creds = fetch_raw_gateway_credentials()
    assert creds["gateway_token"] == "ast_live_from_sm_123"
    assert "waffle-dominic" in creds["firestore_sa_key_json"]


def test_chat_store_manager_invalid_sa_key_fail_fast(monkeypatch):
    from app.firestore_chat import ChatStoreManager
    from app.config import settings

    ChatStoreManager.set_store(None)
    monkeypatch.setattr(settings, "firestore_sa_key_json", "{broken-json")

    with pytest.raises(RuntimeError, match="Configured Firestore service account key is invalid"):
        ChatStoreManager.get_store()


def test_fetch_raw_gateway_credentials_lru_cache(monkeypatch):
    import json
    from unittest.mock import MagicMock
    from app.security import fetch_raw_gateway_credentials

    # Clear lru_cache first
    if hasattr(fetch_raw_gateway_credentials, "cache_clear"):
        fetch_raw_gateway_credentials.cache_clear()

    monkeypatch.delenv("GATEWAY_TOKEN", raising=False)
    monkeypatch.delenv("FIRESTORE_SA_KEY_JSON", raising=False)
    monkeypatch.setenv("GCP_PROJECT", "initbtn-510706")

    mock_sm_client = MagicMock()
    mock_response = MagicMock()
    mock_response.payload.data = json.dumps({"gateway_token": "cached_tok", "firestore_sa_key": {}}).encode("utf-8")
    mock_sm_client.access_secret_version.return_value = mock_response

    mock_sm_module = MagicMock()
    mock_sm_module.SecretManagerServiceClient.return_value = mock_sm_client

    import sys
    monkeypatch.setitem(sys.modules, "google.cloud.secretmanager", mock_sm_module)

    # 1. First call -> executes fetch
    creds1 = fetch_raw_gateway_credentials()
    assert creds1["gateway_token"] == "cached_tok"
    assert mock_sm_client.access_secret_version.call_count == 1

    # 2. Second call -> served from lru_cache, no additional SecretManager API call
    creds2 = fetch_raw_gateway_credentials()
    assert creds2["gateway_token"] == "cached_tok"
    assert mock_sm_client.access_secret_version.call_count == 1
    assert hasattr(fetch_raw_gateway_credentials, "cache_info")
    assert fetch_raw_gateway_credentials.cache_info().hits >= 1


def test_chat_session_upsert_timestamp_guard(setup_chat_test_environment):
    from unittest.mock import MagicMock
    from app.firestore_chat import ChatSessionMeta, FirestoreChatStore

    client = TestClient(app)
    token = setup_chat_test_environment["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create initial session with lastActiveAt = 5000
    res = client.post(
        "/v1/gateway/chat/sessions",
        headers=headers,
        json={
            "sessionId": "sess-guard",
            "senderName": "GuardUser",
            "contact": "guard@example.com",
            "createdAt": 1000,
            "lastActiveAt": 5000,
            "unreadAdminCount": 0,
        },
    )
    assert res.status_code == 200

    # 2. Upsert with lastActiveAt = 0 (e.g. client omits or defaults to 0) -> must preserve 5000
    res_zero = client.post(
        "/v1/gateway/chat/sessions",
        headers=headers,
        json={
            "sessionId": "sess-guard",
            "senderName": "GuardUser",
            "contact": "guard@example.com",
            "createdAt": 1000,
            "lastActiveAt": 0,
            "unreadAdminCount": 1,
        },
    )
    assert res_zero.status_code == 200

    detail = client.get("/v1/gateway/chat/sessions/sess-guard", headers=headers).json()
    assert detail["session"]["lastActiveAt"] == 5000
    assert detail["session"]["unreadAdminCount"] == 1

    # 3. Upsert with older lastActiveAt = 3000 -> must preserve 5000
    res_older = client.post(
        "/v1/gateway/chat/sessions",
        headers=headers,
        json={
            "sessionId": "sess-guard",
            "senderName": "GuardUser",
            "contact": "guard@example.com",
            "createdAt": 1000,
            "lastActiveAt": 3000,
            "unreadAdminCount": 2,
        },
    )
    assert res_older.status_code == 200

    detail2 = client.get("/v1/gateway/chat/sessions/sess-guard", headers=headers).json()
    assert detail2["session"]["lastActiveAt"] == 5000
    assert detail2["session"]["unreadAdminCount"] == 2

    # 4. Upsert with newer lastActiveAt = 7000 -> updates to 7000
    res_newer = client.post(
        "/v1/gateway/chat/sessions",
        headers=headers,
        json={
            "sessionId": "sess-guard",
            "senderName": "GuardUser",
            "contact": "guard@example.com",
            "createdAt": 1000,
            "lastActiveAt": 7000,
            "unreadAdminCount": 3,
        },
    )
    assert res_newer.status_code == 200

    detail3 = client.get("/v1/gateway/chat/sessions/sess-guard", headers=headers).json()
    assert detail3["session"]["lastActiveAt"] == 7000
    assert detail3["session"]["unreadAdminCount"] == 3

    # 5. Unit mock test for FirestoreChatStore.upsert_session guard
    mock_client = MagicMock()
    mock_coll = MagicMock()
    mock_doc = MagicMock()
    mock_client.collection.return_value = mock_coll
    mock_coll.document.return_value = mock_doc

    # Mock existing doc with lastActiveAt = 5000
    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {"lastActiveAt": 5000}
    mock_doc.get.return_value = mock_snap

    fs_store = FirestoreChatStore(client=mock_client)
    # Upsert with lastActiveAt = 0
    fs_sess = ChatSessionMeta(sessionId="s-fs", senderName="User", createdAt=1, lastActiveAt=0)
    fs_store.upsert_session(fs_sess)
    # The set call should NOT overwrite lastActiveAt with 0 (or should omit it / retain 5000)
    args, kwargs = mock_doc.set.call_args
    set_dict = args[0]
    assert set_dict["lastActiveAt"] == 5000


def test_chat_session_telegram_topic_id_support(setup_chat_test_environment):
    client = TestClient(app)
    token = setup_chat_test_environment["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Upsert session with telegramTopicId = 777
    res = client.post(
        "/v1/gateway/chat/sessions",
        headers=headers,
        json={
            "sessionId": "sess-topic-1",
            "senderName": "TopicUser",
            "contact": "topic@example.com",
            "createdAt": 1000,
            "lastActiveAt": 1000,
            "unreadAdminCount": 0,
            "telegramTopicId": 777,
        },
    )
    assert res.status_code == 200

    # 2. Detail returns telegramTopicId
    res_detail = client.get("/v1/gateway/chat/sessions/sess-topic-1", headers=headers)
    assert res_detail.status_code == 200
    detail = res_detail.json()
    assert detail["session"]["telegramTopicId"] == 777

    # 3. List returns telegramTopicId
    res_list = client.get("/v1/gateway/chat/sessions?limit=10", headers=headers)
    assert res_list.status_code == 200
    sessions = res_list.json()["sessions"]
    matching = [s for s in sessions if s["sessionId"] == "sess-topic-1"]
    assert len(matching) == 1
    assert matching[0]["telegramTopicId"] == 777




