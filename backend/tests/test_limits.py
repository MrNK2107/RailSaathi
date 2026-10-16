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
    # /refine takes a strict schema (Phase 3): the old raw `requirements` dict is rejected outright ...
    assert c.post("/api/journey/refine", json={"requirements": {"origin": "y" * 101}}).status_code == 422
    # ... and free-text fields still honour MAX_MESSAGE_CHARS.
    r = c.post("/api/journey/refine", json={"plan_id": "plan_abcdefgh", "preferred_train_name_or_number": "y" * 70})
    assert r.status_code == 401  # under the limit: passes the length check, then needs a session token
    c2 = make_client(max_message_chars=50)
    r = c2.post("/api/journey/refine", json={"plan_id": "plan_abcdefgh", "preferred_train_name_or_number": "y" * 51})
    assert r.status_code == 422 and r.json()["error"]["details"]["field"] == "preferred_train_name_or_number"


def test_lock_ttl_must_outlive_llm_deadline():
    import pytest
    from app.config import Settings
    with pytest.raises(ValueError):
        Settings(_env_file=None, llm_overall_deadline_seconds=30, session_lock_ttl_ms=30_000)
    Settings(_env_file=None, llm_overall_deadline_seconds=30, session_lock_ttl_ms=55_000)


def test_lock_ttl_must_also_cover_the_railradar_call_budget():
    """A turn runs the LLM and then a RailRadar search under the lock; a reassessment runs two RailRadar batches."""
    import pytest
    from app.config import Settings
    with pytest.raises(ValueError, match="RailRadar call budget"):  # 20 s LLM + 30 s search + 10 s margin
        Settings(_env_file=None, railradar_call_budget_seconds=30, session_lock_ttl_ms=45_000)
    with pytest.raises(ValueError):  # reassess: 2 x 25 s + 10 s margin > 55 s even though 20 + 25 + 10 fits
        Settings(_env_file=None, railradar_call_budget_seconds=25, session_lock_ttl_ms=55_000)
    ok = Settings(_env_file=None, railradar_call_budget_seconds=25, session_lock_ttl_ms=60_000)
    assert ok.planner_turn_budget_seconds == 50
    assert Settings(_env_file=None).planner_turn_budget_seconds == 35  # 20 s LLM + 15 s RailRadar


def test_railradar_batches_run_under_the_configured_budget():
    from app.config import Settings
    from app.container import build_data_sources
    provider, disruptions, _ = build_data_sources(Settings(_env_file=None, RAILWAY_DATA_MODE="railradar",
                                                           railradar_api_key="k", railradar_call_budget_seconds=7))
    assert provider._budget == 7 and disruptions._budget == 7


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
