"""Ticketing agent: scripted MockChatLLM turns, budgets, turn deadline, degraded path, provenance, citations and
conversation history keyed by the verified session."""

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.agent.controller import OFFICIAL_LINKS, AgentController
from app.agent.fencing import is_allowed_url
from app.agent.keyword_llm import KeywordChatLLM
from app.clock import FixedClock
from app.config import Settings
from app.container import build_container
from app.knowledge.ingest import ingest
from app.llm.base import LLMError, LLMErrorKind, LLMTurn, ToolCall
from app.llm.mock import MockChatLLM
from app.main import create_app
from tests.conftest import FIXED_NOW

RAC_CALL = ToolCall(name="explain_reservation_status", args={"status_code": "RAC"})


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("kb") / "knowledge.db"
    ingest(path)
    return str(path)


def controller(llm, db, **kw):
    return AgentController(llm, db, now=lambda: FIXED_NOW, **kw)


# --- controller -------------------------------------------------------------------------------------------

def test_grounded_answer_with_citations_and_live_provenance(db):
    llm = MockChatLLM([[RAC_CALL], "RAC lets you board with a shared berth. Source: https://www.indianrail.gov.in/"])
    res = controller(llm, db).process_message("What is RAC?")
    assert res.status == "answered"
    assert res.tool_calls_made == 1 and res.rounds_used == 2
    assert res.sources, "answers must cite their sources"
    for source in res.sources:
        assert is_allowed_url(source["url"]) and source["as_of"] == "2026-10-14"
    assert res.provenance["mode"] == "live"
    assert "not official" in res.provenance["note"]


def test_rule_based_agent_reports_fallback_provenance(db):
    res = controller(KeywordChatLLM(), db).process_message("When does Tatkal booking open?")
    assert res.status == "answered"
    assert res.provenance["mode"] == "fallback"
    assert any(s["source_id"] == "src-ir-tatkal-scheme" for s in res.sources)
    assert "10:00" in res.answer


def test_tool_call_budget_is_enforced(db):
    llm = MockChatLLM([[RAC_CALL, RAC_CALL, RAC_CALL], "summary"])
    res = controller(llm, db, max_tool_calls=2).process_message("RAC?")
    assert res.tool_calls_made == 2
    outputs = [r.response["untrusted_tool_output"] for r in llm.calls[1][-1].tool_results]
    assert "budget_exhausted" in outputs[2]
    assert any(t["event"] == "budget_exceeded" for t in res.trace)


def test_round_budget_ends_with_a_tool_free_summary(db):
    llm = MockChatLLM([[RAC_CALL], [RAC_CALL], "Here is what I found."])
    res = controller(llm, db, max_rounds=2).process_message("RAC?")
    assert res.status == "execution_limit_reached"
    assert res.answer == "Here is what I found."
    assert llm.tools[-1] == []  # the final call offers no tools
    assert len(llm.calls) == 3


def test_round_budget_summary_failure_degrades(db):
    llm = MockChatLLM([[RAC_CALL], LLMError(LLMErrorKind.TIMEOUT)])
    res = controller(llm, db, max_rounds=1).process_message("RAC?")
    assert res.status == "unavailable"


class _ClockAdvancingLLM(MockChatLLM):
    def __init__(self, script, clock, step):
        super().__init__(script)
        self._clock, self._step = clock, step

    def generate(self, messages, tools, deadline):
        self._clock[0] += self._step
        return super().generate(messages, tools, deadline)


def test_turn_deadline_stops_further_rounds(db):
    now = [0.0]
    llm = _ClockAdvancingLLM([[RAC_CALL], [RAC_CALL], "late answer"], now, step=6.0)
    res = controller(llm, db, deadline_seconds=10.0, deadline_clock=lambda: now[0]).process_message("RAC?")
    assert res.status == "unavailable"
    assert len(llm.calls) == 2  # the third round never starts
    assert res.provenance["mode"] == "unavailable"


@pytest.mark.parametrize("error", [LLMError(LLMErrorKind.THROTTLED), LLMError(LLMErrorKind.TIMEOUT),
                                   RuntimeError("boom with secret text")])
def test_llm_failure_degrades_to_official_links(db, error):
    res = controller(MockChatLLM([error]), db).process_message("What is RAC?")
    assert res.status == "unavailable"
    assert res.message == "guidance unavailable"
    assert res.links == OFFICIAL_LINKS and all(is_allowed_url(link["url"]) for link in res.links)
    assert res.provenance["mode"] == "unavailable"
    assert "secret" not in res.answer


def test_answer_urls_are_filtered(db):
    llm = MockChatLLM([LLMTurn(text="Pay at [this page](https://evil.example/pay) or https://www.irctc.co.in/nget/train-search")])
    res = controller(llm, db).process_message("How do I book?")
    assert "evil" not in res.answer
    assert "https://www.irctc.co.in/nget/train-search" in res.answer


# --- API ---------------------------------------------------------------------------------------------------

def make_client(chat_llm=None, redis=None, **overrides) -> TestClient:
    settings = Settings(_env_file=None, **overrides)
    container = build_container(settings, clock=FixedClock(FIXED_NOW), use_configured_llm=False,
                                chat_llm=chat_llm, redis=redis)
    return TestClient(create_app(settings, container))


def test_api_degraded_shape():
    r = make_client(MockChatLLM([LLMError(LLMErrorKind.MODEL_ERROR)])).post("/api/chat", json={"message": "RAC?"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "unavailable"
    assert body["message"] == "guidance unavailable"
    assert [link["url"] for link in body["links"]] == [link["url"] for link in OFFICIAL_LINKS]
    assert body["provenance"]["mode"] == "unavailable"


def test_api_rule_based_answer_has_fallback_provenance_and_citations():
    body = make_client().post("/api/chat", json={"message": "What does RAC mean?"}).json()
    assert body["status"] == "answered"
    assert body["provenance"]["mode"] == "fallback"
    assert body["sources"] and all(s["url"] and s["as_of"] for s in body["sources"])
    assert "links" not in body


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_conversation_history_is_bound_to_the_session(backend):
    redis = fakeredis.FakeStrictRedis(decode_responses=True) if backend == "redis" else None
    llm = MockChatLLM(["first answer", "second answer", "third answer"])
    c = make_client(llm, redis=redis)
    first = c.post("/api/chat", json={"message": "What is RAC?"}).json()
    token, conv = first["session_token"], first["conversation_id"]
    assert token and conv

    second = c.post("/api/chat", json={"message": "And WL?", "conversation_id": conv},
                    headers={"X-Session-Token": token}).json()
    assert second["conversation_id"] == conv
    texts = [(m.role, m.text) for m in llm.calls[1]]
    assert texts == [("user", "What is RAC?"), ("assistant", "first answer"), ("user", "And WL?")]

    # Same conversation id without the token: a new session, no access to the history.
    third = c.post("/api/chat", json={"message": "hi", "conversation_id": conv}).json()
    assert third["session_token"] != token
    assert [m.text for m in llm.calls[2]] == ["hi"]


def test_degraded_turns_are_not_stored():
    llm = MockChatLLM([LLMError(LLMErrorKind.TIMEOUT), "ok"])
    c = make_client(llm)
    first = c.post("/api/chat", json={"message": "q1"}).json()
    c.post("/api/chat", json={"message": "q2", "conversation_id": first["conversation_id"]},
           headers={"X-Session-Token": first["session_token"]})
    assert [m.text for m in llm.calls[1]] == ["q2"]


def test_invalid_session_token_is_rejected():
    r = make_client().post("/api/chat", json={"message": "RAC?"}, headers={"X-Session-Token": "forged.sig"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_session_token"


def test_conversation_id_is_validated():
    r = make_client().post("/api/chat", json={"message": "RAC?", "conversation_id": "a:b/../c"})
    assert r.status_code == 422


def test_history_is_bounded():
    llm = MockChatLLM([f"answer {i}" for i in range(6)])
    c = make_client(llm, max_history_messages=4)
    first = c.post("/api/chat", json={"message": "q0"}).json()
    headers = {"X-Session-Token": first["session_token"]}
    for i in range(1, 6):
        c.post("/api/chat", json={"message": f"q{i}", "conversation_id": first["conversation_id"]}, headers=headers)
    assert len(llm.calls[-1]) == 5  # 4 stored messages + the new question
