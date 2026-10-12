"""
RailSathi AI — Knowledge Retrieval Engine

SQLite FTS5-based retrieval with source provenance, freshness checks,
and relevance ranking.
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.knowledge.database import get_connection

# Staleness threshold: guidance verified more than 6 months ago is flagged
STALENESS_DAYS = 180

SUPPORTED_TOPICS = [
    "ticket_class",
    "reservation_status",
    "booking_process",
    "cancellation_refund",
]

# Common abbreviation expansions for search normalization
ABBREVIATIONS = {
    "sl": "sleeper SL",
    "3a": "third AC 3A",
    "2a": "second AC 2A",
    "1a": "first AC 1A",
    "cc": "chair car CC",
    "3e": "third economy 3E",
    "cnf": "confirmed CNF",
    "rac": "reservation against cancellation RAC",
    "wl": "waitlisted waitlist WL",
    "gnwl": "general waitlist GNWL",
    "rlwl": "remote location waitlist RLWL",
    "pqwl": "pooled quota waitlist PQWL",
    "tdr": "ticket deposit receipt TDR",
    "pnr": "PNR passenger name record",
    "irctc": "IRCTC Indian Railway Catering Tourism",
}


def normalize_query(query: str) -> str:
    """
    Normalize a search query by expanding common railway abbreviations
    without destroying the original terms.
    """
    words = query.strip().split()
    expanded = []
    for word in words:
        lower = word.lower().strip(".,?!")
        if lower in ABBREVIATIONS:
            expanded.append(ABBREVIATIONS[lower])
        else:
            expanded.append(word)
    return " ".join(expanded)


def _check_freshness(last_verified: str | None) -> dict:
    """Check if a record's verification date indicates staleness."""
    if not last_verified:
        return {"is_stale": True, "days_since_verification": None, "warning": "No verification date available"}

    try:
        verified_date = datetime.fromisoformat(last_verified)
        if verified_date.tzinfo is None:
            verified_date = verified_date.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days = (now - verified_date).days
        is_stale = days > STALENESS_DAYS
        return {
            "is_stale": is_stale,
            "days_since_verification": days,
            "warning": f"Information was last verified {days} days ago. Please verify current rules at official sources." if is_stale else None,
        }
    except (ValueError, TypeError):
        return {"is_stale": True, "days_since_verification": None, "warning": "Invalid verification date"}


def search_guidance(
    db_path: str,
    query: str,
    topic: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """
    Search the knowledge base for relevant ticketing guidance.

    Args:
        db_path: Path to the SQLite database.
        query: The passenger's search query.
        topic: Optional topic filter (one of SUPPORTED_TOPICS).
        limit: Maximum number of results (1-20).

    Returns:
        A dict with results, source metadata, freshness info, and retrieval status.
    """
    # Validate inputs
    if not query or not query.strip():
        return {
            "results": [],
            "total_found": 0,
            "retrieval_status": "error",
            "error": "Query cannot be empty",
            "evidence_sufficient": False,
        }

    limit = max(1, min(limit, 20))

    if topic and topic not in SUPPORTED_TOPICS:
        return {
            "results": [],
            "total_found": 0,
            "retrieval_status": "error",
            "error": f"Unsupported topic: {topic}. Supported: {SUPPORTED_TOPICS}",
            "evidence_sufficient": False,
        }

    # Normalize query for better recall
    normalized = normalize_query(query)

    conn = get_connection(db_path)
    try:
        results = _execute_fts_search(conn, normalized, topic, limit)

        # If FTS finds nothing, try a LIKE-based fallback
        if not results:
            results = _execute_like_search(conn, query, topic, limit)

        # Enrich with source metadata and freshness
        enriched = []
        sources_used = {}
        any_stale = False

        for row in results:
            source = _get_source_for_result(conn, row["source_id"])
            freshness = _check_freshness(row.get("last_verified_at"))
            if freshness["is_stale"]:
                any_stale = True

            entry = {
                "guidance_id": row["guidance_id"],
                "topic": row["topic"],
                "question": row["question"],
                "answer_text": row["answer_text"],
                "conditions": _parse_json_field(row.get("conditions")),
                "exceptions": _parse_json_field(row.get("exceptions")),
                "source_excerpt": row.get("source_excerpt"),
                "last_verified_at": row.get("last_verified_at"),
                "freshness": freshness,
                "source": source,
            }
            enriched.append(entry)

            if source:
                sources_used[source["source_id"]] = source

        evidence_sufficient = len(enriched) > 0

        return {
            "results": enriched,
            "total_found": len(enriched),
            "sources": list(sources_used.values()),
            "retrieval_status": "success",
            "evidence_sufficient": evidence_sufficient,
            "any_stale": any_stale,
            "staleness_warning": "Some information may be outdated. Please verify at official sources." if any_stale else None,
        }

    except Exception as e:
        return {
            "results": [],
            "total_found": 0,
            "retrieval_status": "error",
            "error": f"Retrieval failed: {type(e).__name__}",
            "evidence_sufficient": False,
        }
    finally:
        conn.close()


def _execute_fts_search(
    conn: sqlite3.Connection, query: str, topic: str | None, limit: int
) -> list[dict]:
    """Execute FTS5 search with optional topic filter."""
    # Build FTS query — use simple token matching
    fts_query = " OR ".join(
        f'"{w}"' for w in query.split() if len(w) > 1
    )
    if not fts_query:
        return []

    if topic:
        sql = """
            SELECT g.*, rank
            FROM guidance_fts fts
            JOIN guidance g ON g.rowid = fts.rowid
            WHERE guidance_fts MATCH ? AND g.topic = ? AND g.status = 'active'
            ORDER BY rank
            LIMIT ?
        """
        rows = conn.execute(sql, (fts_query, topic, limit)).fetchall()
    else:
        sql = """
            SELECT g.*, rank
            FROM guidance_fts fts
            JOIN guidance g ON g.rowid = fts.rowid
            WHERE guidance_fts MATCH ? AND g.status = 'active'
            ORDER BY rank
            LIMIT ?
        """
        rows = conn.execute(sql, (fts_query, limit)).fetchall()

    return [dict(r) for r in rows]


def _execute_like_search(
    conn: sqlite3.Connection, query: str, topic: str | None, limit: int
) -> list[dict]:
    """Fallback LIKE-based search when FTS finds nothing."""
    words = [w.strip() for w in query.split() if len(w.strip()) > 1]
    if not words:
        return []

    conditions = []
    params = []
    for word in words[:5]:  # Limit to 5 words to avoid huge queries
        conditions.append(
            "(g.question LIKE ? OR g.answer_text LIKE ? OR g.topic LIKE ?)"
        )
        like_param = f"%{word}%"
        params.extend([like_param, like_param, like_param])

    where = " OR ".join(conditions)
    if topic:
        where = f"({where}) AND g.topic = ?"
        params.append(topic)

    sql = f"""
        SELECT g.* FROM guidance g
        WHERE g.status = 'active' AND ({where})
        LIMIT ?
    """
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _get_source_for_result(conn: sqlite3.Connection, source_id: str) -> dict | None:
    """Retrieve source metadata for a guidance result."""
    row = conn.execute(
        "SELECT * FROM sources WHERE source_id = ?", (source_id,)
    ).fetchone()
    if row:
        source = dict(row)
        # Don't expose content_hash to frontend
        source.pop("content_hash", None)
        return source
    return None


def _parse_json_field(value: str | list | None) -> list:
    """Parse a JSON field that may be a string, list, or None."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
