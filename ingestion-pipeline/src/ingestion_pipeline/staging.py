"""Common staging envelope + JSONL persistence.

Every lane normalizes raw exports into `StagingRecord` and appends them to
`data/staging/<lane>.jsonl`. Records are deduped by `source_id`; a changed
`content_hash` replaces the prior record so re-drops update cleanly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ingestion_pipeline import config


class StagingRecord(BaseModel):
    """One normalized source document awaiting Supabase sync."""

    lane: str
    source_system: str
    source_id: str
    content_hash: str
    sensitivity: str = "internal"
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_title: str | None = None
    source_url: str | None = None
    occurred_at: str | None = None
    participants: list[str] = Field(default_factory=list)
    raw_text: str = ""
    embed_text: str = ""


def staging_path(lane: str) -> Path:
    return config.STAGING_DIR / f"{lane}.jsonl"


def read_records(path: Path) -> list[StagingRecord]:
    if not path.exists():
        return []
    records: list[StagingRecord] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(StagingRecord.model_validate_json(line))
    return records


def _write_all(path: Path, records: list[StagingRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.model_dump_json() + "\n")


def stage_records(lane: str, incoming: list[StagingRecord]) -> dict[str, int]:
    """Merge records into the lane's staging file, deduped by source_id.

    Returns counts: added, updated (content_hash changed), unchanged.
    """
    path = staging_path(lane)
    existing = {r.source_id: r for r in read_records(path)}
    counts = {"added": 0, "updated": 0, "unchanged": 0}

    for record in incoming:
        prior = existing.get(record.source_id)
        if prior is None:
            counts["added"] += 1
        elif prior.content_hash != record.content_hash:
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
            continue
        existing[record.source_id] = record

    _write_all(path, list(existing.values()))
    return counts
