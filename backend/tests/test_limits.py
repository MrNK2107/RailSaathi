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
