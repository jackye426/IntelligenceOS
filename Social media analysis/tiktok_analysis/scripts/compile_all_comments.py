"""
Compile all raw comments into a single readable text file: ALL_COMMENTS.txt

Format per video:
  - date, views, title
  - each comment: likes | text  (sorted by likes desc)
  - theme + sentiment labels from build_analysis output where available

Also writes ALL_COMMENTS.csv for spreadsheet analysis.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ANALYSIS = ROOT / "analysis"
OUT_TXT = DATA / "ALL_COMMENTS.txt"
OUT_CSV = DATA / "ALL_COMMENTS.csv"


def load_catalog() -> dict[str, dict]:
    catalog: dict[str, dict] = {}
    for p in sorted(DATA.glob("docmap_catalog_since_*.json")):
        for e in json.loads(p.read_text(encoding="utf-8")):
            vid = e.get("video_id", "")
            if vid and vid not in catalog:
                catalog[vid] = e
    return catalog


def load_labeled(video_id: str) -> dict[str, dict]:
    """Return cid -> label dict from comments_labeled_{id}.json."""
    p = ANALYSIS / f"comments_labeled_{video_id}.json"
    if not p.exists():
        return {}
    rows = json.loads(p.read_text(encoding="utf-8"))
    return {str(r.get("cid", "")): r for r in rows}


def main() -> None:
    catalog = load_catalog()

    # Collect all raw comment files, sorted by post date (newest first)
    raw_dir = DATA / "comments_raw"
    raw_files = sorted(raw_dir.glob("*.json"))

    def sort_key(p: Path) -> str:
        return catalog.get(p.stem, {}).get("post_datetime_utc", "") or ""

    raw_files.sort(key=sort_key, reverse=True)

    txt_lines: list[str] = [
        "# Docmap TikTok — ALL COMMENTS",
        f"# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"# Videos with comment files: {len(raw_files)}",
        "",
    ]

    csv_rows: list[dict] = []

    total_comments = 0
    for path in raw_files:
        vid = path.stem
        comments = json.loads(path.read_text(encoding="utf-8"))
        if not comments:
            continue

        cat = catalog.get(vid, {})
        views = int(cat.get("view_count") or 0)
        post_date = (cat.get("post_date_utc") or "unknown")
        title = (cat.get("title") or cat.get("description") or "")[:80]
        url = cat.get("url") or f"https://www.tiktok.com/@docmap/video/{vid}"

        labeled = load_labeled(vid)

        comments_sorted = sorted(comments, key=lambda c: int(c.get("digg_count") or 0), reverse=True)

        txt_lines.append("=" * 72)
        txt_lines.append(f"VIDEO: {vid}")
        txt_lines.append(f"Date:  {post_date}  |  Views: {views:,}  |  Comments fetched: {len(comments)}")
        txt_lines.append(f"URL:   {url}")
        txt_lines.append(f"Title: {title}")
        txt_lines.append("")

        for c in comments_sorted:
            cid = str(c.get("cid", ""))
            text = (c.get("text") or "").replace("\n", " ").strip()
            likes = int(c.get("digg_count") or 0)
            replies = int(c.get("reply_comment_total") or 0)

            label = labeled.get(cid, {})
            themes = ", ".join(label.get("themes") or [])
            sentiment = label.get("sentiment") or {}
            stance = sentiment.get("stance", "")
            emotion = sentiment.get("primary_emotion", "")

            label_str = f"  [{themes} | {stance} | {emotion}]" if themes else ""
            txt_lines.append(f"  {likes:>5} likes  {replies:>3} replies  |  {text}")
            if label_str:
                txt_lines.append(f"         {label_str}")

            csv_rows.append({
                "video_id": vid,
                "post_date": post_date,
                "views": views,
                "comment_likes": likes,
                "comment_replies": replies,
                "comment_text": text,
                "themes": themes,
                "stance": stance,
                "emotion": emotion,
                "url": url,
            })
            total_comments += 1

        txt_lines.append("")

    txt_lines.extend(["=" * 72, f"END — {total_comments} comments across {len(raw_files)} videos", "=" * 72])

    OUT_TXT.write_text("\n".join(txt_lines), encoding="utf-8")
    print(f"Wrote {OUT_TXT}  ({total_comments} comments)")

    fields = ["video_id", "post_date", "views", "comment_likes", "comment_replies",
              "comment_text", "themes", "stance", "emotion", "url"]
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(csv_rows)
    print(f"Wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
