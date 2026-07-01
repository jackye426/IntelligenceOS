"""Compile ALL_COMMENTS.txt and CSV from comments_raw."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from marketing_pipeline import config
from marketing_pipeline.tiktok.stages.collect_catalog import load_catalog


def write_comments_digest(
    *,
    out_txt: Path | None = None,
    out_csv: Path | None = None,
) -> dict[str, int]:
    catalog = load_catalog(config.CATALOG_DIR)
    raw_dir = config.COMMENTS_RAW_DIR
    out_txt = out_txt or config.ALL_COMMENTS_TXT
    out_csv = out_csv or config.EXPORTS_DIR / "ALL_COMMENTS.csv"
    out_txt.parent.mkdir(parents=True, exist_ok=True)

    raw_files = sorted(raw_dir.glob("*.json"), key=lambda p: catalog.get(p.stem, {}).get("post_date_utc", ""), reverse=True)

    lines = [
        "# Docmap TikTok — ALL COMMENTS",
        f"# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"# Videos with comment files: {len(raw_files)}",
        "",
    ]
    csv_rows: list[dict] = []
    total = 0

    for path in raw_files:
        video_id = path.stem
        comments = json.loads(path.read_text(encoding="utf-8"))
        if not comments:
            continue

        cat = catalog.get(video_id, {})
        views = int(cat.get("view_count") or 0)
        post_date = cat.get("post_date_utc") or "unknown"
        title = (cat.get("title") or cat.get("description") or "")[:80]
        url = cat.get("url") or f"https://www.tiktok.com/@docmap/video/{video_id}"

        labeled_path = config.ANALYSIS_DIR / f"comments_labeled_{video_id}.json"
        labeled_by_cid: dict[str, dict] = {}
        if labeled_path.exists():
            for row in json.loads(labeled_path.read_text(encoding="utf-8")):
                labeled_by_cid[str(row.get("cid", ""))] = row

        comments_sorted = sorted(comments, key=lambda c: int(c.get("digg_count") or 0), reverse=True)

        lines.extend(
            [
                "=" * 72,
                f"VIDEO: {video_id}",
                f"Date:  {post_date}  |  Views: {views:,}  |  Comments fetched: {len(comments)}",
                f"URL:   {url}",
                f"Title: {title}",
                "",
            ]
        )

        for comment in comments_sorted:
            cid = str(comment.get("cid", ""))
            text = (comment.get("text") or "").replace("\n", " ").strip()
            likes = int(comment.get("digg_count") or 0)
            replies = int(comment.get("reply_comment_total") or 0)
            label = labeled_by_cid.get(cid, {})
            themes = ", ".join(label.get("themes") or [])
            sentiment = label.get("sentiment") or {}
            stance = sentiment.get("stance", "")
            emotion = sentiment.get("primary_emotion", "")
            label_str = f"  [{themes} | {stance} | {emotion}]" if themes else ""
            lines.append(f"  {likes:>5} likes  {replies:>3} replies  |  {text}")
            if label_str:
                lines.append(f"         {label_str}")
            csv_rows.append(
                {
                    "video_id": video_id,
                    "post_date": post_date,
                    "views": views,
                    "comment_likes": likes,
                    "comment_replies": replies,
                    "comment_text": text,
                    "themes": themes,
                    "stance": stance,
                    "emotion": emotion,
                    "url": url,
                }
            )
            total += 1
        lines.append("")

    lines.extend(["=" * 72, f"END — {total} comments across {len(raw_files)} videos", "=" * 72])
    out_txt.write_text("\n".join(lines), encoding="utf-8")

    fields = [
        "video_id",
        "post_date",
        "views",
        "comment_likes",
        "comment_replies",
        "comment_text",
        "themes",
        "stance",
        "emotion",
        "url",
    ]
    with out_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(csv_rows)

    return {"videos": len(raw_files), "comments": total, "txt": str(out_txt)}
