"""
RailSathi AI — Knowledge Ingestion

Builds the knowledge SQLite file from `seed_data.py`. Runs at image-build time in the backend Dockerfile
(`python -m app.knowledge.ingest`); the running service opens the result read-only.

The file is built from scratch in a temporary file next to the target and moved into place atomically, so a
rebuild never leaves removed records behind and readers never see a half-written database. The hash of the seed
data is stored in the `meta` table; `ensure_knowledge_db` (development and tests only) rebuilds when the file is
missing or was built from different seed data.
"""

import hashlib
import json
import logging
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from app.config import DB_PATH
from app.knowledge.database import (
    content_hash,
    get_connection,
    get_writable_connection,
    init_database,
    insert_guidance,
    insert_source,
)
from app.knowledge.seed_data import GUIDANCE_RECORDS, SOURCES

log = logging.getLogger("railsaathi.knowledge")


def seed_hash() -> str:
    blob = json.dumps({"sources": SOURCES, "guidance": GUIDANCE_RECORDS}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def ingest(db_path: Path | None = None) -> dict:
    """Build the database at `db_path` (default: DB_PATH) from the seed data. Returns the loaded counts."""
    target = Path(db_path or DB_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)
    try:
        init_database(tmp)
        with closing(get_writable_connection(tmp)) as conn:
            for source in SOURCES:
                insert_source(conn, {**source, "content_hash": source.get("content_hash")
                                     or content_hash(source["title"])})
            for record in GUIDANCE_RECORDS:
                insert_guidance(conn, record)
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('seed_hash', ?)", (seed_hash(),))
            conn.commit()
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return {"sources_loaded": len(SOURCES), "guidance_loaded": len(GUIDANCE_RECORDS)}


def is_current(db_path: Path) -> bool:
    """True when `db_path` exists and was built from the current seed data."""
    try:
        with closing(get_connection(db_path)) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'seed_hash'").fetchone()
    except sqlite3.Error:
        return False
    return row is not None and row["value"] == seed_hash()


def ensure_knowledge_db(db_path: Path) -> bool:
    """Development/test convenience: (re)build the file when it is missing or stale. Returns True if built.
    Never called in production, where the file comes from the image build and is read-only."""
    if is_current(db_path):
        return False
    log.info("Building the knowledge base at %s", db_path)
    ingest(db_path)
    return True


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_PATH
    counts = ingest(out)
    print(f"Knowledge base built at {out}: {counts['sources_loaded']} sources, "
          f"{counts['guidance_loaded']} guidance records.")
