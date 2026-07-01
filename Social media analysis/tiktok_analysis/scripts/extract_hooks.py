"""
Extract the spoken hook (first sentence) from every video in ALL_COMPLETE_TRANSCRIPTS,
pair it with view counts from the catalog, and write a hook analysis CSV + text report.

Hook = first meaningful sentence of the Whisper transcript.
Also captures the TikTok caption's opening line as the "text hook" (what appears on cover/caption).
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TRANSCRIPTS = DATA / "transcripts"


def first_sentence(text: str) -> str:
    """Return the first sentence of a transcript, capped at 200 chars."""
    text = text.strip()
    if not text:
        return ""
    # Split on sentence-ending punctuation followed by whitespace or end-of-string
    m = re.search(r"[.!?](?:\s|$)", text)
    if m:
        return text[: m.start() + 1].strip()
    # No punctuation found — return first 200 chars or first line
    first_line = text.split("\n")[0].strip()
    return first_line[:200]


def first_line_of_description(desc: str) -> str:
    """Return the first sentence/line of a TikTok caption."""
    desc = desc.strip()
    if not desc:
        return ""
    # Try first sentence
    m = re.search(r"[.!?](?:\s|$)", desc)
    if m and m.start() < 200:
        return desc[: m.start() + 1].strip()
    return desc.split("\n")[0].strip()[:200]


def load_catalog() -> dict[str, dict]:
    """Load all catalog JSON files and merge into a lookup by video_id."""
    videos: dict[str, dict] = {}
    for p in sorted(DATA.glob("docmap_catalog_since_*.json")):
        for entry in json.loads(p.read_text(encoding="utf-8")):
            vid = entry.get("video_id", "")
            if vid and vid not in videos:
                videos[vid] = entry
    return videos


def load_analytics() -> dict[str, dict]:
    """Pull view counts from ALL_COMPLETE_TRANSCRIPTS or metrics_refresh.json."""
    analytics: dict[str, dict] = {}

    # Prefer metrics_refresh.json (has richer data)
    metrics_path = DATA / "metrics_refresh.json"
    if metrics_path.exists():
        for m in json.loads(metrics_path.read_text(encoding="utf-8")):
            vid = str(m.get("video_id", ""))
            if vid:
                analytics[vid] = m

    # Also parse ALL_COMPLETE_TRANSCRIPTS for view counts (covers videos not in metrics)
    all_txt = TRANSCRIPTS / "ALL_COMPLETE_TRANSCRIPTS.txt"
    if all_txt.exists():
        text = all_txt.read_text(encoding="utf-8")
        blocks = re.split(r"={40,}", text)
        for block in blocks:
            vid_m = re.search(r"id (\d{15,})", block)
            views_m = re.search(r"Views:\s*([\d,]+)", block)
            date_m = re.search(r"Post date \(UTC\):\s*(\S+)", block)
            if vid_m and views_m:
                vid = vid_m.group(1)
                views = int(views_m.group(1).replace(",", ""))
                if vid not in analytics:
                    analytics[vid] = {}
                analytics[vid].setdefault("view_count", views)
                if date_m:
                    analytics[vid].setdefault("post_date_utc", date_m.group(1))

    return analytics


def extract_hooks() -> list[dict]:
    catalog = load_catalog()
    analytics = load_analytics()

    results = []
    for json_path in sorted(TRANSCRIPTS.glob("*.json")):
        vid = json_path.stem
        if not vid.isdigit():
            continue

        data = json.loads(json_path.read_text(encoding="utf-8"))
        full_text = data.get("full_text", "")
        if not full_text and isinstance(data, list):
            full_text = " ".join(s.get("text", "") for s in data).strip()

        spoken_hook = first_sentence(full_text) if full_text else "(no speech)"

        # Get description from catalog or metadata
        cat = catalog.get(vid, {})
        description = cat.get("description", "")
        title = cat.get("title", "")

        # Fall back to yt_meta if catalog missing
        if not description:
            meta_path = DATA / "yt_meta" / f"{vid}.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                description = meta.get("description", "")
                title = meta.get("title", "")

        text_hook = first_line_of_description(description or title)

        an = analytics.get(vid, {})
        views = an.get("view_count", "")
        post_date = an.get("post_date_utc", cat.get("post_date_utc", ""))

        results.append({
            "video_id": vid,
            "post_date": post_date,
            "views": views,
            "spoken_hook": spoken_hook,
            "text_hook_caption": text_hook,
            "url": f"https://www.tiktok.com/@docmap/video/{vid}",
        })

    results.sort(key=lambda r: str(r.get("post_date", "")), reverse=True)
    return results


def write_csv(results: list[dict]) -> Path:
    out = DATA / "hook_analysis.csv"
    fields = ["video_id", "post_date", "views", "spoken_hook", "text_hook_caption", "url"]
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)
    return out


def write_report(results: list[dict]) -> Path:
    out = DATA / "hook_analysis_report.txt"
    lines = [
        "# Docmap TikTok — Hook Analysis\n",
        "# Spoken hook = first sentence of Whisper ASR transcript\n",
        "# Text hook   = first sentence of TikTok caption/description\n",
        f"# Videos: {len(results)}\n\n",
    ]

    for r in results:
        views = f"{r['views']:,}" if isinstance(r['views'], int) else str(r['views'])
        lines.append(f"{'='*70}\n")
        lines.append(f"  {r['post_date']}  |  {views} views\n")
        lines.append(f"  {r['url']}\n")
        lines.append(f"\n  SPOKEN HOOK:  {r['spoken_hook']}\n")
        lines.append(f"  TEXT HOOK:    {r['text_hook_caption']}\n")

    lines.append(f"\n{'='*70}\n")
    lines.append("# A/B PAIRS — same content, different hook\n")
    lines.append("# (MRI example highlighted below)\n\n")

    # Auto-detect likely A/B pairs: same spoken content, different views
    # Group by rough spoken hook similarity
    mri_ids = {"7644863912545881366", "7634579404131241239", "7641301413062102294"}
    excision_ids = {"7641554459755089154", "7631220659770690818"}

    for label, pair_ids in [("MRI — who reads it matters", mri_ids), ("Excision vs ablation", excision_ids)]:
        pair = [r for r in results if r["video_id"] in pair_ids]
        if len(pair) >= 2:
            lines.append(f"  --- {label} ---\n")
            for r in sorted(pair, key=lambda x: x.get("views", 0) if isinstance(x.get("views"), int) else 0, reverse=True):
                views = f"{r['views']:,}" if isinstance(r['views'], int) else str(r['views'])
                lines.append(f"  {views:>10} views  |  {r['post_date']}  |  {r['url']}\n")
                lines.append(f"    SPOKEN: {r['spoken_hook']}\n")
                lines.append(f"    TEXT:   {r['text_hook_caption']}\n\n")

    out.write_text("".join(lines), encoding="utf-8")
    return out


def main() -> None:
    results = extract_hooks()
    csv_path = write_csv(results)
    report_path = write_report(results)
    print(f"Extracted hooks for {len(results)} videos")
    print(f"Wrote {csv_path}")
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
