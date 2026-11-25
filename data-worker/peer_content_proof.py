"""One bounded, operator-triggered proof for each approved public TikTok account.

No metrics fetch/write, embeddings, comments, scheduler or media retention.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

from social_metrics import TIKTOK_PEERS, owner_scope_for

ACCOUNTS = ("endobowelsurgeon", *TIKTOK_PEERS)
OPENING_SECONDS = (0, 0.5, 1, 2)
_CAPTURE_TOOL = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
                 "--no-warnings", "--socket-timeout", "20", "--retries", "0"]


def _process(args, *, timeout):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, timeout=timeout).stdout


def _collect(url, handle, video_id):
    from marketing_pipeline.tiktok.stages.transcribe_video import transcribe_media

    with TemporaryDirectory(prefix="peer-proof-") as work:
        path = Path(work)
        # Metadata supplied by the existing third-party provider is not a
        # freshness signal; the proof takes its counts only from the saved view.
        payload = json.loads(_process([*_CAPTURE_TOOL, "--dump-single-json", "--skip-download", url],
                                      timeout=60))
        if str(payload.get("id") or "") != video_id or payload.get("webpage_url") != url:
            raise ValueError("unexpected video identity")
        uploader = str(payload.get("uploader_id") or payload.get("uploader") or "").lower().lstrip("@")
        if uploader and uploader != handle:
            raise ValueError("unexpected account identity")
        caption = (payload.get("description") or "").strip()
        if not caption:
            raise ValueError("no caption to verify in proof")
        _process([*_CAPTURE_TOOL, "-f", "b[vcodec!=none][acodec!=none]/bv*+ba/b",
                  "--merge-output-format", "mp4", "--max-filesize", "80M",
                  "-o", str(path / "media.%(ext)s"), url], timeout=180)
        media = [p for p in path.glob("media.*") if p.suffix in {".mp4", ".webm", ".mov"}]
        if len(media) != 1 or media[0].stat().st_size > 80 * 1024**2:
            raise ValueError("no bounded media for proof")
        segments, transcript = transcribe_media(media[0], video_id, caption_hint=caption, out_dir=path)
        if not segments or not transcript:
            raise ValueError("no timestamped speech for proof")
        results = []
        for second in OPENING_SECONDS:
            image = path / "frame.png"
            _process(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(second), "-i", str(media[0]),
                      "-frames:v", "1", "-vf", "scale='min(1080,iw)':-2", "-y", str(image)], timeout=30)
            text = _process(["tesseract", str(image), "stdout"], timeout=30).decode("utf-8").strip()
            results.append({"second": second, "text": text})
        return caption, segments, transcript, results


def _rows(client, table, fields, filters):
    query = client.table(table).select(fields)
    for field, value in filters.items():
        query = query.eq(field, value)
    return query.limit(2).execute().data or []


def _proof_one(client, handle, video_id, *, collect, apply):
    scope = owner_scope_for("tiktok", handle)
    url = f"https://www.tiktok.com/@{handle}/video/{video_id}"
    filters = {"platform": "tiktok", "account_handle": handle,
               "owner_scope": scope, "platform_post_id": video_id}
    rows = _rows(client, "content_posts", "id,post_url,metadata,updated_at", filters)
    if len(rows) != 1 or rows[0]["post_url"] != url:
        raise ValueError("expected exactly one scoped, canonical catalogue row")
    view = ("latest_social_metric_snapshots" if handle == "endobowelsurgeon"
            else "latest_public_tiktok_peer_metrics")
    metrics = _rows(client, view, "captured_at,metrics", {**filters, "source": "yt_dlp"})
    if len(metrics) != 1 or not metrics[0].get("captured_at") or not metrics[0].get("metrics"):
        raise ValueError("no scoped yt_dlp metrics")
    captured = datetime.fromisoformat(metrics[0]["captured_at"].replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - captured).total_seconds()
    if not 0 <= age <= 48 * 3600:
        raise ValueError("yt_dlp snapshot is not fresh")
    if not apply:
        return {"status": "ready", "captured_at": captured.isoformat()}

    row = rows[0]
    baseline = row.get("metadata") or {}
    if baseline.get("peer_evidence_version") == 1:
        return {"status": "already_stored", "captured_at": captured.isoformat()}
    version = row.get("updated_at")
    if not version:
        raise ValueError("catalogue row has no write guard")
    caption, segments, transcript, frames = collect(url, handle, video_id)
    if not (caption and segments and transcript and any(f.get("text") for f in frames)):
        raise ValueError("proof requires caption, timed speech and visible opening text")
    ocr_evidence = {"scope": "opening_frames", "model": "tesseract",
                    "frames": [f["second"] for f in frames], "results": frames}
    metadata = {**baseline, "transcript_segments": segments,
                "transcript_status": "transcribed", "ocr_evidence": ocr_evidence,
                "peer_evidence_version": 1}
    query = client.table("content_posts").update({
        "caption": caption, "transcript": transcript, "metadata": metadata,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", row["id"]).eq("updated_at", version)
    for field, value in filters.items():
        query = query.eq(field, value)
    if len(query.execute().data or []) != 1:
        raise RuntimeError("scoped write did not update exactly one row")
    saved = _rows(client, "content_posts", "caption,transcript,metadata", filters)
    if (len(saved) != 1 or saved[0]["caption"] != caption or saved[0]["transcript"] != transcript
            or saved[0]["metadata"].get("transcript_segments") != segments
            or saved[0]["metadata"].get("ocr_evidence") != ocr_evidence):
        raise RuntimeError("evidence readback mismatch")
    return {"status": "stored", "captured_at": captured.isoformat(),
            "caption_chars": len(caption), "segments": len(segments),
            "opening_frames": len(frames), "frames_with_text": sum(bool(f["text"]) for f in frames)}


def run_proof(client, targets, *, apply=False, collect=_collect):
    if set(targets) != set(ACCOUNTS) or any(
        not isinstance(value, str) or not re.fullmatch(r"[0-9]{5,25}", value)
        for value in targets.values()
    ) or len(set(targets.values())) != len(ACCOUNTS):
        raise ValueError("provide one distinct numeric video ID for each approved account")
    results = {}
    for handle in ACCOUNTS:
        try:
            results[handle] = _proof_one(client, handle, targets[handle], collect=collect, apply=apply)
        except Exception as exc:
            # Do not log post text, raw provider errors or service credentials.
            results[handle] = {"status": "failed", "error_type": type(exc).__name__}
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for handle in ACCOUNTS:
        parser.add_argument(f"--{handle}", dest=handle, required=True)
    parser.add_argument("--apply", action="store_true", help="Collect and write proof; default is DB preflight only")
    args = vars(parser.parse_args())
    apply = args.pop("apply")
    from common.supabase_client import get_client

    result = run_proof(get_client(), args, apply=apply)
    print(json.dumps(result, indent=2))
    return int(any(row["status"] == "failed" for row in result.values()))


if __name__ == "__main__":
    raise SystemExit(main())
