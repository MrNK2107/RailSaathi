from tests.test_api import make_client, new_session


def test_message_over_settings_limit_is_422():
    c = make_client(max_message_chars=100)
    sid = new_session(c)
    r = c.post(f"/api/planner/sessions/{sid}/messages", json={"message": "x" * 101})
    assert r.status_code == 422 and r.json()["error"]["code"] == "message_too_long"
    assert c.post(f"/api/planner/sessions/{sid}/messages", json={"message": "x" * 100}).status_code == 200


def test_chat_and_goal_prompt_limits():
    c = make_client(max_message_chars=100)
    assert c.post("/api/chat", json={"message": "x" * 101}).status_code == 422
    assert c.post("/api/journey/plan", json={"prompt": "x" * 101}).status_code == 422


def test_body_limit_applies_to_every_post_and_to_chunked_bodies():
    c = make_client(max_body_bytes=1024)
    assert c.post("/api/chat", json={"message": "hi", "pad": "y" * 2000}).status_code == 413
    assert c.post("/api/journey/plan", json={"prompt": "hi", "pad": "y" * 2000}).status_code == 413

    def chunks():  # no Content-Length: counted while streaming
        for _ in range(4):
            yield b"z" * 500

    r = c.post("/api/chat", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


def test_refine_applies_message_limit_to_free_text():
    c = make_client(max_message_chars=100)
    assert c.post("/api/journey/refine", json={"preferred_class": "x" * 101}).status_code == 422
    r = c.post("/api/journey/refine", json={"requirements": {"origin": "y" * 101}})
    assert r.status_code == 422 and r.json()["error"]["details"]["field"] == "requirements.origin"


def test_lock_ttl_must_outlive_llm_deadline():
    import pytest
    from app.config import Settings
    with pytest.raises(ValueError):
        Settings(_env_file=None, llm_overall_deadline_seconds=30, session_lock_ttl_ms=30_000)
    Settings(_env_file=None, llm_overall_deadline_seconds=30, session_lock_ttl_ms=40_000)


def test_lock_timeout_maps_to_503_session_busy():
    import fakeredis
    from app.sessions.redis_store import RedisSessionStore
    from tests.test_rate_limit import make
    r = fakeredis.FakeStrictRedis(decode_responses=True)
    c = make(redis=r, session_lock_wait_seconds=0.1)
    store = c.app.state.container.planner.store
    assert isinstance(store, RedisSessionStore)
    created = c.post("/api/planner/sessions", json={}).json()
    c.headers["X-Session-Token"] = created["session_token"]
    with store.lock(created["session_id"]):
        r2 = c.post(f"/api/planner/sessions/{created['session_id']}/messages", json={"message": "hi"})
    assert r2.status_code == 503 and r2.json()["error"]["code"] == "session_busy"
