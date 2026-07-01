"""Print comment insights across all videos."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ANALYSIS = ROOT / "analysis"

catalog = {}
for p in DATA.glob("docmap_catalog_since_*.json"):
    for e in json.loads(p.read_text(encoding="utf-8")):
        vid = e["video_id"]
        if vid not in catalog:
            catalog[vid] = e

summaries = json.loads((ANALYSIS / "comment_summary_by_video.json").read_text(encoding="utf-8"))
summaries_with = [s for s in summaries if s.get("n_fetched", 0) > 0]
summaries_with.sort(key=lambda s: s["n_fetched"], reverse=True)

print("=== COMMENT VOLUME BY VIDEO (videos with comments only) ===")
for s in summaries_with:
    vid = s["video_id"]
    views = int(catalog.get(vid, {}).get("view_count") or 0)
    cpr = round(s["n_fetched"] / views * 1000, 2) if views else 0
    title = (catalog.get(vid, {}).get("title") or "")[:55]
    n = s["n_fetched"]
    print(f"  {views:>8} views | {n:>4} comments | {cpr:>5} /1k views | {title}")

print()
print("=== CROSS-VIDEO THEME TOTALS ===")
all_themes: Counter = Counter()
for s in summaries_with:
    for theme, count in s.get("theme_distribution", {}).items():
        all_themes[theme] += count
total = sum(all_themes.values())
for theme, count in all_themes.most_common():
    print(f"  {count:>4} ({round(count/total*100):>2}%)  {theme}")

print()
print("=== EMOTION DISTRIBUTION ===")
all_emotions: Counter = Counter()
for s in summaries_with:
    for emo, count in s.get("emotion_distribution", {}).items():
        all_emotions[emo] += count
total_e = sum(all_emotions.values())
for emo, count in all_emotions.most_common():
    print(f"  {count:>4} ({round(count/total_e*100):>2}%)  {emo}")

print()
print("=== STANCE DISTRIBUTION ===")
all_stances: Counter = Counter()
for s in summaries_with:
    for stance, count in s.get("stance_distribution", {}).items():
        all_stances[stance] += count
total_st = sum(all_stances.values())
for stance, count in all_stances.most_common():
    print(f"  {count:>4} ({round(count/total_st*100):>2}%)  {stance}")

print()
print("=== HIGH COMMENT-RATE VIDEOS (comments per 1k views) ===")
rates = []
for s in summaries_with:
    vid = s["video_id"]
    views = int(catalog.get(vid, {}).get("view_count") or 0)
    if views >= 500:
        cpr = round(s["n_fetched"] / views * 1000, 2)
        rates.append((cpr, vid, views, s["n_fetched"], catalog.get(vid, {}).get("title", "")[:60]))
for cpr, vid, views, n, title in sorted(rates, reverse=True)[:10]:
    print(f"  {cpr:>5} /1k  |  {views:>8} views  |  {n:>3} comments  |  {title}")

print()
print("=== TOP COMMENTS ACROSS ALL VIDEOS ===")
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
top = json.loads((ANALYSIS / "top_comments_labeled.json").read_text(encoding="utf-8"))
top.sort(key=lambda c: c.get("digg_count", 0), reverse=True)
for c in top[:15]:
    vid = c.get("video_id", "")
    views = int(catalog.get(vid, {}).get("view_count") or 0)
    themes = ", ".join(c.get("themes", []))
    text = (c.get("text") or "").replace("\n", " ")[:120]
    print(f"  {c['digg_count']:>5} likes | {views:>8} views | [{themes}]")
    print(f"    \"{text}\"")
