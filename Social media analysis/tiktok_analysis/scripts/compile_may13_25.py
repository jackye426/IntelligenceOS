"""Compile May 13-25 transcripts into a single file."""
import csv
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"

catalog = list(csv.DictReader(open(DATA / "docmap_catalog_may13_to_may25.csv", encoding="utf-8-sig")))

out_lines = ["# Docmap TikTok Transcripts: May 13-25, 2026\n"]

for row in sorted(catalog, key=lambda r: r["post_date_utc"]):
    aid = row["video_id"]
    complete = DATA / "transcripts" / f"{aid}_COMPLETE.txt"
    out_lines.append("\n" + "=" * 70 + "\n")
    if complete.exists():
        out_lines.append(complete.read_text(encoding="utf-8"))
    else:
        out_lines.append(f"video_id: {aid}\n")
        out_lines.append(f"url: {row['url']}\n")
        out_lines.append(f"date: {row['post_date_utc']}\n")
        out_lines.append("\n(No usable speech transcript — likely carousel/slideshow)\n")
        out_lines.append(f"\n## TikTok description\n\n{row['description']}\n")

out = DATA / "transcripts" / "may13_to_may25_ALL_TRANSCRIPTS.txt"
out.write_text("".join(out_lines), encoding="utf-8")
print(f"Wrote {out}")
print(f"Total posts: {len(catalog)}")
for row in sorted(catalog, key=lambda r: r["post_date_utc"]):
    aid = row["video_id"]
    complete = DATA / "transcripts" / f"{aid}_COMPLETE.txt"
    status = "transcribed" if complete.exists() else "no speech / skipped"
    print(f"  {row['post_date_utc']}  {aid}  [{status}]")
