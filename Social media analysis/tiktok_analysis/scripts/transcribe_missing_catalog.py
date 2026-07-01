"""
Transcribe TikTok videos listed in docmap_missing_from_tracker_since_*.csv.

Uses the same Whisper + carousel filter as run_pipeline.py (no transcript files
are kept when is_garbage_transcript is true).
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def load_run_pipeline():
    path = Path(__file__).resolve().parent / "run_pipeline.py"
    spec = importlib.util.spec_from_file_location("run_pipeline", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--csv",
        type=Path,
        default=DATA / "docmap_missing_from_tracker_since_20260420.csv",
        help="CSV from fetch_docmap_catalog.py (in_content_tracker=no rows)",
    )
    ap.add_argument(
        "--whisper-model",
        default="small",
        help="faster-whisper model name",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-download and overwrite existing transcript files",
    )
    args = ap.parse_args()

    rp = load_run_pipeline()

    if not args.csv.exists():
        raise SystemExit(f"Missing CSV: {args.csv} — run fetch_docmap_catalog.py first")

    rows_in = list(csv.DictReader(args.csv.open(encoding="utf-8-sig", newline="")))
    results: list[dict] = []

    for row in rows_in:
        aid = (row.get("video_id") or "").strip()
        if not aid:
            continue
        tr_json = DATA / "transcripts" / f"{aid}.json"
        if tr_json.exists() and not args.force:
            print(f"skip existing transcript {aid}", flush=True)
            results.append({"video_id": aid, "status": "skipped_existing"})
            continue

        print(f"--- {aid}", flush=True)
        try:
            meta = rp.run_yt_dlp_json(aid)
        except subprocess.CalledProcessError as e:
            print(f"  yt-dlp meta failed: {e}", flush=True)
            results.append({"video_id": aid, "status": "meta_failed"})
            continue

        media = rp.existing_media(aid)
        if media is None:
            try:
                media = rp.download_media(aid)
                print(f"  downloaded {media.name}", flush=True)
            except subprocess.CalledProcessError as e:
                print(f"  download failed: {e}", flush=True)
                results.append({"video_id": aid, "status": "download_failed"})
                continue

        try:
            _rows, full_text = rp.transcribe(
                media,
                aid,
                model_size=args.whisper_model,
                caption_hint=meta.get("description"),
            )
        except Exception as e:
            print(f"  transcribe error: {e}", flush=True)
            results.append({"video_id": aid, "status": "transcribe_error", "error": str(e)})
            continue

        if not full_text.strip():
            results.append({"video_id": aid, "status": "skipped_carousel_or_no_speech"})
            continue

        rp.write_complete_transcript(
            aid,
            full_text,
            title=meta.get("title"),
            description=meta.get("description"),
            webpage_url=meta.get("webpage_url"),
        )
        print(f"  ok ({len(full_text)} chars)", flush=True)
        results.append({"video_id": aid, "status": "transcribed", "chars": len(full_text)})

    out = DATA / "transcribe_missing_catalog_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out}", flush=True)

    ok = sum(1 for r in results if r.get("status") == "transcribed")
    sk = sum(1 for r in results if r.get("status") == "skipped_carousel_or_no_speech")
    print(f"Transcribed: {ok}, skipped (carousel/no speech): {sk}", flush=True)


if __name__ == "__main__":
    main()
