"""File-based human review queue (v1 per DATA_INGESTION_PLANS schema note).

Records that a lane cannot classify confidently are staged in
`data/staging/review_queue.jsonl` instead of the lane file. Approving moves
the record into its lane's staging file; rejecting drops it.
"""

from __future__ import annotations

from ingestion_pipeline import config
from ingestion_pipeline.staging import StagingRecord, read_records, stage_records, _write_all


def queue_for_review(records: list[StagingRecord]) -> dict[str, int]:
    return stage_records("review_queue", records)


def list_pending() -> list[StagingRecord]:
    return read_records(config.REVIEW_QUEUE)


def _resolve(source_id: str, *, approve: bool) -> StagingRecord:
    pending = list_pending()
    match = next((r for r in pending if r.source_id == source_id), None)
    if match is None:
        raise SystemExit(f"No pending review record with source_id={source_id}")

    remaining = [r for r in pending if r.source_id != source_id]
    _write_all(config.REVIEW_QUEUE, remaining)

    if approve:
        stage_records(match.lane, [match])
    return match


def approve(source_id: str) -> StagingRecord:
    return _resolve(source_id, approve=True)


def reject(source_id: str) -> StagingRecord:
    return _resolve(source_id, approve=False)
