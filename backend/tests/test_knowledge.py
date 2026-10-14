"""Knowledge base: built by ingest, opened read-only, every rule attributed to an official page with as_of."""

import os
import re
import sqlite3
from contextlib import closing
from urllib.parse import urlsplit

import pytest

from app.api.ticketing import _read_sources
from app.knowledge import ingest as ingest_module
from app.knowledge.database import get_connection
from app.knowledge.ingest import ensure_knowledge_db, ingest, is_current
from app.knowledge.retrieval import search_guidance
from app.knowledge.seed_data import AS_OF, GUIDANCE_RECORDS, SOURCES
from app.tools.ticketing import execute_tool

OFFICIAL_DOMAINS = ("irctc.co.in", "indianrail.gov.in", "indianrailways.gov.in")


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "knowledge.db"
    ingest(path)
    return path


def _official(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS)


# --- seed data --------------------------------------------------------------------------------------------

def test_every_source_is_an_official_page_with_as_of():
    for source in SOURCES:
        assert _official(source["source_url"]), source["source_id"]
        assert source["as_of"] == AS_OF


def test_every_rule_cites_a_known_source_and_has_as_of():
    source_ids = {s["source_id"] for s in SOURCES}
    topics = {r["topic"] for r in GUIDANCE_RECORDS}
    assert {"ticket_class", "reservation_status", "booking_process", "cancellation_refund"} <= topics
    for record in GUIDANCE_RECORDS:
        assert record["source_id"] in source_ids, record["guidance_id"]
        assert record["as_of"] == AS_OF and record["source_excerpt"]


def test_seed_data_states_no_fares_or_refund_amounts():
    money = re.compile(r"(₹|\bRs\.?\s*\d|\bINR\b|\d+\s*%)")
    for record in GUIDANCE_RECORDS:
        text = " ".join([record["answer_text"], *record["conditions"], *record["exceptions"]])
        assert not money.search(text), record["guidance_id"]


# --- read-only database -----------------------------------------------------------------------------------

def test_connection_is_read_only_without_wal(db):
    with closing(get_connection(db)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal"
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM guidance")
    assert not os.path.exists(str(db) + "-wal")


def test_missing_database_is_not_created_and_retrieval_degrades(tmp_path):
    missing = tmp_path / "nope.db"
    with pytest.raises(sqlite3.OperationalError):
        get_connection(missing)
    assert not missing.exists()
    result = search_guidance(str(missing), "RAC")
    assert result["retrieval_status"] == "error" and result["error_code"] == "unavailable"


def test_read_sources_closes_its_connection(db, tmp_path):
    assert len(_read_sources(db)) == len(SOURCES)
    replacement = tmp_path / "other.db"
    ingest(replacement)
    os.replace(replacement, db)  # fails on Windows if a connection to `db` were still open


def test_fts_query_with_quotes_does_not_break_search(db):
    result = search_guidance(str(db), 'what is "RAC')
    assert result["retrieval_status"] == "success" and result["results"]


# --- build ------------------------------------------------------------------------------------------------

def test_rebuild_replaces_stale_content(db, monkeypatch):
    assert is_current(db)
    assert ensure_knowledge_db(db) is False
    monkeypatch.setattr(ingest_module, "GUIDANCE_RECORDS", GUIDANCE_RECORDS[:2])
    assert not is_current(db)
    assert ensure_knowledge_db(db) is True
    with closing(get_connection(db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM guidance").fetchone()[0] == 2


# --- citations --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("tool,args,source_id", [
    ("explain_ticket_class", {"class_code": "3A"}, "src-irctc-train-search"),
    ("explain_reservation_status", {"status_code": "WL"}, "src-ir-pnr-enquiry"),
    ("get_cancellation_refund_guidance", {"question": "tatkal refund"}, "src-ir-refund-rules"),
    ("search_ticketing_guidance", {"query": "Tatkal booking open"}, "src-ir-tatkal-scheme"),
])
def test_tool_results_carry_citations(db, tool, args, source_id):
    result = execute_tool(tool, args, str(db))
    assert result["status"] == "success" and result["evidence_sufficient"]
    assert source_id in {s["source_id"] for s in result["sources"]}
    for source in result["sources"]:
        assert _official(source["source_url"]) and source["as_of"] == AS_OF
    entries = result.get("results") or result["primary_class"]["results"]
    assert all(e["source_url"] and e["as_of"] == AS_OF for e in entries)


def test_output_url_allowlist_matches_the_official_source_domains():
    from app.agent.fencing import ALLOWED_URL_DOMAINS

    assert set(ALLOWED_URL_DOMAINS) == set(OFFICIAL_DOMAINS)
