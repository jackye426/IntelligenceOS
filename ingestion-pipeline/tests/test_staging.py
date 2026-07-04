"""Staging envelope + JSONL dedupe behavior."""

import ingestion_pipeline.config as config
from ingestion_pipeline.staging import StagingRecord, read_records, stage_records, staging_path


def _record(source_id: str, text: str) -> StagingRecord:
    from ingestion_pipeline.shared.hashing import content_hash

    return StagingRecord(
        lane="test_lane",
        source_system="test",
        source_id=source_id,
        content_hash=content_hash(text),
        raw_text=text,
        embed_text=text,
    )


def test_stage_records_dedupes_by_source_id(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STAGING_DIR", tmp_path)

    first = stage_records("test_lane", [_record("a", "one"), _record("b", "two")])
    assert first == {"added": 2, "updated": 0, "unchanged": 0}

    # Re-staging identical content is a no-op; changed content replaces.
    second = stage_records("test_lane", [_record("a", "one"), _record("b", "TWO!")])
    assert second == {"added": 0, "updated": 1, "unchanged": 1}

    records = read_records(staging_path("test_lane"))
    assert len(records) == 2
    assert {r.source_id: r.raw_text for r in records}["b"] == "TWO!"
