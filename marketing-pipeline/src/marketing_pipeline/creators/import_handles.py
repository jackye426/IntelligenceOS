"""Manual handle import — first discovery adapter."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from marketing_pipeline.creators.paths import normalise_handle, pending_tiktok_user_id
from marketing_pipeline.creators.runs import finish_run, start_run
from marketing_pipeline.creators.store import get_store

SLICE = "manual"


def import_handles(
    path: Path,
    *,
    slice_name: str = SLICE,
    store=None,
    source: str = "cli",
) -> dict[str, Any]:
    store = store or get_store()
    run = start_run("import-handles", source=source, params={"file": str(path)}, store=store)
    counters = {"rows": 0, "inserted": 0, "existing": 0, "skipped": 0}
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames or "handle" not in {h.lower() for h in reader.fieldnames}:
                # allow a bare one-column file
                fh.seek(0)
                raw_lines = [line.strip() for line in fh if line.strip() and not line.startswith("#")]
                rows = [{"handle": line.lstrip("@")} for line in raw_lines]
                if rows and rows[0]["handle"].lower() == "handle":
                    rows = rows[1:]
            else:
                rows = list(reader)

        for row in rows:
            counters["rows"] += 1
            handle = normalise_handle(row.get("handle") or row.get("Handle") or "")
            if not handle:
                counters["skipped"] += 1
                continue
            tiktok_user_id = (row.get("tiktok_user_id") or "").strip() or pending_tiktok_user_id(handle)
            existing = store.get("creator_profiles", handle=handle)
            if existing:
                store.update(
                    "creator_profiles",
                    {
                        "discovery_count": int(existing.get("discovery_count") or 1) + 1,
                        "seed_slices": list({*(existing.get("seed_slices") or []), slice_name}),
                    },
                    id=existing["id"],
                )
                counters["existing"] += 1
                continue
            store.insert(
                "creator_profiles",
                {
                    "tiktok_user_id": tiktok_user_id,
                    "handle": handle,
                    "profile_url": f"https://www.tiktok.com/@{handle}",
                    "stage": "discovered",
                    "work_status": "ready",
                    "seed_slices": [slice_name],
                    "best_seed_priority": int(row.get("priority") or 50),
                    "discovery_count": 1,
                    "provenance": {"source": "import-handles", "file": str(path)},
                },
            )
            counters["inserted"] += 1

        status = "completed" if counters["rows"] == counters["inserted"] + counters["existing"] + counters["skipped"] else "degraded"
        if counters["rows"] and counters["inserted"] + counters["existing"] == 0:
            status = "failed"
        finish_run(run["id"], status=status, counters=counters, store=store)
        return {"run_id": run["id"], "status": status, "counters": counters}
    except Exception as exc:  # noqa: BLE001
        finish_run(run["id"], status="failed", counters=counters, error=str(exc), store=store)
        raise
