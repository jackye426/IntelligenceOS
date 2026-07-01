"""
Full @docmap refresh: catalog pull, stats update, transcribe new videos, recompile master file.

  python scripts/refresh_docmap.py
  python scripts/refresh_docmap.py --since 2026-04-20
  python scripts/refresh_docmap.py --skip-transcribe   # stats only
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TRANS = DATA / "transcripts"
SCRIPTS = Path(__file__).resolve().parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def existing_complete_ids() -> set[str]:
    return {
        p.name.replace("_COMPLETE.txt", "")
        for p in TRANS.glob("*_COMPLETE.txt")
        if p.name != "ALL_COMPLETE_TRANSCRIPTS.txt"
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Refresh @docmap catalog, stats, transcripts.")
    ap.add_argument("--since", default="2026-04-20", help="UTC date filter YYYY-MM-DD")
    ap.add_argument("--skip-transcribe", action="store_true")
    ap.add_argument("--skip-compile", action="store_true")
    ap.add_argument("--whisper-model", default="small")
    args = ap.parse_args()

    fetch_mod = load_module("fetch_docmap_catalog", SCRIPTS / "fetch_docmap_catalog.py")
    rp = load_module("run_pipeline", SCRIPTS / "run_pipeline.py")

    slug = args.since.replace("-", "")
    print(f"=== 1/4 Fetch @docmap catalog (since {args.since} UTC) ===", flush=True)
    subprocess.check_call(
        [
            sys.executable,
            str(SCRIPTS / "fetch_docmap_catalog.py"),
            "--since",
            args.since,
        ]
    )

    catalog_path = DATA / f"docmap_catalog_since_{slug}.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    have = existing_complete_ids()
    need_transcribe = [r for r in catalog if r["video_id"] not in have]

    print(f"=== 2/4 Refresh stats for {len(catalog)} catalog videos ===", flush=True)
    metrics = []
    for row in catalog:
        aid = row["video_id"]
        try:
            meta = rp.run_yt_dlp_json(aid)
        except subprocess.CalledProcessError as e:
            print(f"  meta failed {aid}: {e}", flush=True)
            continue
        views = int(meta.get("view_count") or 0)
        likes = int(meta.get("like_count") or 0)
        comments = int(meta.get("comment_count") or 0)
        shares = int(meta.get("repost_count") or 0)
        saves = int(str(meta.get("save_count") or "0").replace(",", "") or 0)
        dur = float(meta.get("duration") or 0)
        metrics.append(
            {
                "video_id": aid,
                "post_date_utc": row.get("post_date_utc"),
                "url": row.get("url"),
                "title": meta.get("title") or row.get("title"),
                "description": meta.get("description") or row.get("description"),
                "duration_sec": dur,
                "view_count": views,
                "like_count": likes,
                "comment_count": comments,
                "share_count": shares,
                "save_count": saves,
                "like_per_1k_views": round(1000 * likes / views, 4) if views else None,
                "comment_per_1k_views": round(1000 * comments / views, 4) if views else None,
                "share_per_1k_views": round(1000 * shares / views, 4) if views else None,
                "save_per_1k_views": round(1000 * saves / views, 4) if views else None,
                "has_complete_transcript": aid in have,
            }
        )

    metrics.sort(key=lambda x: x.get("view_count") or 0, reverse=True)
    metrics_path = DATA / "metrics_refresh.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  wrote {metrics_path}", flush=True)

    transcribe_log: list[dict] = []
    if not args.skip_transcribe and need_transcribe:
        print(
            f"=== 3/4 Transcribe {len(need_transcribe)} new video(s) ===",
            flush=True,
        )
        for row in need_transcribe:
            aid = row["video_id"]
            print(f"--- {aid} ({row.get('post_date_utc')})", flush=True)
            try:
                meta = rp.run_yt_dlp_json(aid)
            except subprocess.CalledProcessError:
                transcribe_log.append({"video_id": aid, "status": "meta_failed"})
                continue
            media = rp.existing_media(aid)
            if media is None:
                try:
                    media = rp.download_media(aid)
                    print(f"  downloaded {media.name}", flush=True)
                except subprocess.CalledProcessError:
                    transcribe_log.append({"video_id": aid, "status": "download_failed"})
                    continue
            try:
                _rows, full_text = rp.transcribe(
                    media,
                    aid,
                    model_size=args.whisper_model,
                    caption_hint=meta.get("description"),
                )
            except Exception as e:
                transcribe_log.append(
                    {"video_id": aid, "status": "transcribe_error", "error": str(e)}
                )
                continue
            if not full_text.strip():
                transcribe_log.append(
                    {"video_id": aid, "status": "skipped_carousel_or_no_speech"}
                )
                continue
            rp.write_complete_transcript(
                aid,
                full_text,
                title=meta.get("title"),
                description=meta.get("description"),
                webpage_url=meta.get("webpage_url"),
            )
            have.add(aid)
            transcribe_log.append(
                {"video_id": aid, "status": "transcribed", "chars": len(full_text)}
            )
            print(f"  ok ({len(full_text)} chars)", flush=True)
    else:
        print("=== 3/4 Transcribe skipped (none new or --skip-transcribe) ===", flush=True)

    log_path = DATA / "refresh_transcribe_log.json"
    log_path.write_text(
        json.dumps(
            {
                "refreshed_at": datetime.now(timezone.utc).isoformat(),
                "since": args.since,
                "catalog_count": len(catalog),
                "already_had_transcript": len(catalog) - len(need_transcribe),
                "attempted_new": len(need_transcribe),
                "results": transcribe_log,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # Summary CSV: catalog rows missing transcripts
    missing_tr = [r for r in catalog if r["video_id"] not in have]
    miss_path = DATA / f"docmap_no_transcript_since_{slug}.csv"
    if missing_tr:
        with miss_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(missing_tr[0].keys()))
            w.writeheader()
            w.writerows(missing_tr)
    elif miss_path.exists():
        miss_path.unlink()

    # Re-mark transcript flags after any new transcriptions
    for m in metrics:
        m["has_complete_transcript"] = m["video_id"] in have
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.skip_compile:
        print("=== 4/4 Recompile ALL_COMPLETE_TRANSCRIPTS.txt ===", flush=True)
        subprocess.check_call(
            [sys.executable, str(SCRIPTS / "compile_complete_transcripts.py")]
        )

    n_new = sum(1 for x in transcribe_log if x.get("status") == "transcribed")
    n_skip = sum(
        1 for x in transcribe_log if x.get("status") == "skipped_carousel_or_no_speech"
    )
    print("", flush=True)
    print(f"Catalog since {args.since}: {len(catalog)} videos", flush=True)
    print(f"With COMPLETE transcript: {len(have)}", flush=True)
    print(f"Newly transcribed this run: {n_new}", flush=True)
    print(f"Skipped (carousel/no speech): {n_skip}", flush=True)
    print(f"No transcript yet: {len(missing_tr)}", flush=True)
    if missing_tr:
        print(f"  see {miss_path}", flush=True)


if __name__ == "__main__":
    main()
