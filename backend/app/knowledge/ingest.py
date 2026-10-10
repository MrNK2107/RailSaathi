"""
RailSathi AI — Knowledge Ingestion Script

Initializes the database and loads seed data from curated sources.
Safe to run multiple times (uses INSERT OR REPLACE).
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.knowledge.database import init_database, insert_source, insert_guidance, get_connection, content_hash
from app.knowledge.seed_data import SOURCES, GUIDANCE_RECORDS
from app.config import DB_PATH


def ingest(db_path: Path | None = None) -> dict:
    """
    Initialize the database and load all seed data.

    Returns a summary dict with counts of loaded sources and guidance records.
    """
    target = db_path or DB_PATH

    # Ensure the directory exists
    target.parent.mkdir(parents=True, exist_ok=True)

    print(f"Initializing database at: {target}")
    init_database(target)

    conn = get_connection(target)
    try:
        source_count = 0
        for source in SOURCES:
            # Compute content hash if not present
            if not source.get("content_hash"):
                source = {**source, "content_hash": content_hash(source["title"])}
            insert_source(conn, source)
            source_count += 1
            print(f"  Source: {source['source_id']} — {source['title']}")

        guidance_count = 0
        for record in GUIDANCE_RECORDS:
            insert_guidance(conn, record)
            guidance_count += 1
            print(f"  Guidance: {record['guidance_id']} — {record['question'][:60]}...")

        conn.commit()
        print(f"\nIngestion complete: {source_count} sources, {guidance_count} guidance records.")
        return {"sources_loaded": source_count, "guidance_loaded": guidance_count}

    finally:
        conn.close()


if __name__ == "__main__":
    ingest()
