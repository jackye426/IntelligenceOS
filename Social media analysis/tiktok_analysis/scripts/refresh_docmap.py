"""Full @docmap refresh — delegates to marketing-pipeline package stages.

  python scripts/refresh_docmap.py
  python scripts/refresh_docmap.py --since 2026-04-20
  python scripts/refresh_docmap.py --skip-transcribe   # stats only
"""
from __future__ import annotations

import argparse

from marketing_pipeline.tiktok.stages.refresh_legacy import run_legacy_refresh


def main() -> None:
    ap = argparse.ArgumentParser(description="Refresh @docmap catalog, stats, transcripts.")
    ap.add_argument("--since", default="2026-04-20", help="UTC date filter YYYY-MM-DD")
    ap.add_argument("--skip-transcribe", action="store_true")
    ap.add_argument("--skip-compile", action="store_true")
    ap.add_argument("--skip-catalog", action="store_true", help="Skip catalog fetch")
    ap.add_argument("--whisper-model", default=None, help="Whisper model size (default: package config)")
    args = ap.parse_args()

    result = run_legacy_refresh(
        since=args.since,
        skip_transcribe=args.skip_transcribe,
        skip_catalog=args.skip_catalog,
        skip_compile=args.skip_compile,
        whisper_model=args.whisper_model,
    )

    videos = result.get("videos") or {}
    transcribe_log = videos.get("transcribe_log") or []
    n_new = sum(1 for x in transcribe_log if x.get("status") == "transcribed")
    n_skip = sum(1 for x in transcribe_log if x.get("status") == "skipped_carousel_or_no_speech")
    catalog_count = videos.get("catalog_count", 0)
    with_tr = videos.get("with_transcript", 0)
    missing = catalog_count - with_tr

    print("", flush=True)
    print(f"Catalog since {args.since}: {catalog_count} videos", flush=True)
    print(f"With COMPLETE transcript: {with_tr}", flush=True)
    print(f"Newly transcribed this run: {n_new}", flush=True)
    print(f"Skipped (carousel/no speech): {n_skip}", flush=True)
    print(f"No transcript yet: {missing}", flush=True)
    if missing and videos.get("stats", {}).get("metrics_path"):
        slug = args.since.replace("-", "")
        print(f"  see analysis/docmap_no_transcript_since_{slug}.csv", flush=True)
    if not args.skip_compile and result.get("master"):
        print(f"Master file: {result['master'].get('master_path')}", flush=True)


if __name__ == "__main__":
    main()
