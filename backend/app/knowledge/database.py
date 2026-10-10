"""
RailSathi AI — Knowledge Database Schema & Initialization

SQLite database for storing ticketing guidance with full source provenance.
"""

import sqlite3
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Create a database connection with row factory enabled."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_database(db_path: str | Path) -> None:
    """Initialize the database schema. Safe to call multiple times."""
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def content_hash(text: str) -> str:
    """Generate a SHA-256 hash for content integrity checking."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


SCHEMA_SQL = """
-- Sources: authoritative documents that back guidance records
CREATE TABLE IF NOT EXISTS sources (
    source_id       TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    publisher       TEXT NOT NULL DEFAULT 'Indian Railways',
    source_url      TEXT,
    source_type     TEXT NOT NULL DEFAULT 'official_documentation',
    retrieved_at    TEXT NOT NULL,
    last_verified_at TEXT NOT NULL,
    publication_date TEXT,
    effective_from  TEXT,
    effective_until TEXT,
    content_hash    TEXT,
    verification_status TEXT NOT NULL DEFAULT 'manually_verified',
    retrieval_status    TEXT NOT NULL DEFAULT 'success',
    notes           TEXT
);

-- Guidance records: individual Q&A entries with source provenance
CREATE TABLE IF NOT EXISTS guidance (
    guidance_id     TEXT PRIMARY KEY,
    topic           TEXT NOT NULL,
    question        TEXT NOT NULL,
    answer_text     TEXT NOT NULL,
    conditions      TEXT,  -- JSON array of applicable conditions
    exceptions      TEXT,  -- JSON array of exceptions
    source_id       TEXT NOT NULL,
    source_excerpt  TEXT,
    last_verified_at TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

-- Full-text search index on guidance
CREATE VIRTUAL TABLE IF NOT EXISTS guidance_fts USING fts5(
    guidance_id,
    topic,
    question,
    answer_text,
    conditions,
    exceptions,
    content='guidance',
    content_rowid='rowid'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS guidance_ai AFTER INSERT ON guidance BEGIN
    INSERT INTO guidance_fts(rowid, guidance_id, topic, question, answer_text, conditions, exceptions)
    VALUES (new.rowid, new.guidance_id, new.topic, new.question, new.answer_text, new.conditions, new.exceptions);
END;

CREATE TRIGGER IF NOT EXISTS guidance_ad AFTER DELETE ON guidance BEGIN
    INSERT INTO guidance_fts(guidance_fts, rowid, guidance_id, topic, question, answer_text, conditions, exceptions)
    VALUES ('delete', old.rowid, old.guidance_id, old.topic, old.question, old.answer_text, old.conditions, old.exceptions);
END;

CREATE TRIGGER IF NOT EXISTS guidance_au AFTER UPDATE ON guidance BEGIN
    INSERT INTO guidance_fts(guidance_fts, rowid, guidance_id, topic, question, answer_text, conditions, exceptions)
    VALUES ('delete', old.rowid, old.guidance_id, old.topic, old.question, old.answer_text, old.conditions, old.exceptions);
    INSERT INTO guidance_fts(rowid, guidance_id, topic, question, answer_text, conditions, exceptions)
    VALUES (new.rowid, new.guidance_id, new.topic, new.question, new.answer_text, new.conditions, new.exceptions);
END;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_guidance_topic ON guidance(topic);
CREATE INDEX IF NOT EXISTS idx_guidance_source ON guidance(source_id);
CREATE INDEX IF NOT EXISTS idx_guidance_status ON guidance(status);
"""


def insert_source(conn: sqlite3.Connection, source: dict) -> None:
    """Insert or replace a source record."""
    conn.execute(
        """INSERT OR REPLACE INTO sources
           (source_id, title, publisher, source_url, source_type,
            retrieved_at, last_verified_at, publication_date,
            effective_from, effective_until, content_hash,
            verification_status, retrieval_status, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            source["source_id"],
            source["title"],
            source.get("publisher", "Indian Railways"),
            source.get("source_url"),
            source.get("source_type", "official_documentation"),
            source["retrieved_at"],
            source["last_verified_at"],
            source.get("publication_date"),
            source.get("effective_from"),
            source.get("effective_until"),
            source.get("content_hash"),
            source.get("verification_status", "manually_verified"),
            source.get("retrieval_status", "success"),
            source.get("notes"),
        ),
    )


def insert_guidance(conn: sqlite3.Connection, guidance: dict) -> None:
    """Insert or replace a guidance record."""
    conditions = guidance.get("conditions")
    exceptions = guidance.get("exceptions")

    conn.execute(
        """INSERT OR REPLACE INTO guidance
           (guidance_id, topic, question, answer_text, conditions,
            exceptions, source_id, source_excerpt, last_verified_at, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            guidance["guidance_id"],
            guidance["topic"],
            guidance["question"],
            guidance["answer_text"],
            json.dumps(conditions) if isinstance(conditions, list) else conditions,
            json.dumps(exceptions) if isinstance(exceptions, list) else exceptions,
            guidance["source_id"],
            guidance.get("source_excerpt"),
            guidance["last_verified_at"],
            guidance.get("status", "active"),
        ),
    )


def get_source(conn: sqlite3.Connection, source_id: str) -> dict | None:
    """Retrieve a source record by ID."""
    row = conn.execute(
        "SELECT * FROM sources WHERE source_id = ?", (source_id,)
    ).fetchone()
    return dict(row) if row else None


def get_all_sources(conn: sqlite3.Connection) -> list[dict]:
    """Retrieve all source records."""
    rows = conn.execute(
        "SELECT * FROM sources ORDER BY last_verified_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]
