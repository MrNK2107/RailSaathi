import pytest

from app.config import Settings
from app.security.tokens import InvalidSessionToken, SessionTokenSigner, build_signer
from tests.test_api import make_client, new_session

KEY = b"k" * 32


def test_roundtrip_and_session_binding():
    s = SessionTokenSigner(KEY)
    token = s.issue("abc")
    assert s.verify(token) == "abc"
    s.verify_for(token, "abc")
    with pytest.raises(InvalidSessionToken):
        s.verify_for(token, "other")


@pytest.mark.parametrize("mutate", [
    lambda t: t[:-2] + ("AA" if not t.endswith("AA") else "BB"),   # tampered signature
    lambda t: "other" + t[t.index("."):],                          # swapped session id
    lambda t: t.replace(".", ""),                                  # no separator
    lambda t: "",
    lambda t: "x" * 300,
])
def test_tampered_tokens_rejected(mutate):
    s = SessionTokenSigner(KEY)
    with pytest.raises(InvalidSessionToken):
        s.verify(mutate(s.issue("abc")))


def test_token_from_other_key_rejected():
    with pytest.raises(InvalidSessionToken):
        SessionTokenSigner(b"z" * 32).verify(SessionTokenSigner(KEY).issue("abc"))


def test_none_rejected():
    with pytest.raises(InvalidSessionToken):
        SessionTokenSigner(KEY).verify(None)


def test_production_requires_signing_key():
    with pytest.raises(ValueError):
        build_signer(Settings(_env_file=None, app_env="production"))
    assert build_signer(Settings(_env_file=None, app_env="production", session_signing_key="p" * 32))
    assert build_signer(Settings(_env_file=None))  # dev: random key


def test_session_routes_require_matching_token():
    c = make_client()
    created = c.post("/api/planner/sessions", json={}).json()
    sid, token = created["session_id"], created["session_token"]
    assert token and sid in token

    r = c.get(f"/api/planner/sessions/{sid}")
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_session_token"
    assert c.get(f"/api/planner/sessions/{sid}", headers={"X-Session-Token": token[:-3] + "xyz"}).status_code == 401
    assert c.get(f"/api/planner/sessions/{sid}", headers={"X-Session-Token": token}).status_code == 200

    other = new_session(make_client())
    assert c.get(f"/api/planner/sessions/{other}", headers={"X-Session-Token": token}).status_code == 401
    assert c.get(f"/api/planner/sessions/{sid}/audit").status_code == 401


def test_non_ascii_token_is_rejected_not_500():
    s = SessionTokenSigner(KEY)
    for bad in ("abc.éé", "ébc." + s.issue("x").split(".")[1]):
        with pytest.raises(InvalidSessionToken):
            s.verify(bad)
    c = make_client()
    created = c.post("/api/planner/sessions", json={}).json()
    url = f"/api/planner/sessions/{created['session_id']}"
    r = c.get(url, headers={"X-Session-Token": "abc.é".encode("utf-8")})
    assert r.status_code == 401
    assert c.get("/api/planner/reference", headers={"X-Session-Token": "é.é".encode("utf-8")}).status_code == 200
