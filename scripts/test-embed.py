#!/usr/bin/env python3
"""Smoke test: embed one row into document_embeddings with citation metadata."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data-worker"
sys.path.insert(0, str(ROOT))

from common.embeddings import upsert_embedding_chunks  # noqa: E402


def main() -> None:
    entity_id = str(uuid.uuid4())
    written = upsert_embedding_chunks(
        entity_type="smoke_test",
        entity_id=entity_id,
        text="hello world — DocMap MCP embedding smoke test",
        source_table="smoke_test",
        source_title="Embedding smoke test",
        source_url=None,
        metadata={"purpose": "acceptance_check"},
    )
    print({"entity_id": entity_id, "chunks_written": written})


if __name__ == "__main__":
    main()
