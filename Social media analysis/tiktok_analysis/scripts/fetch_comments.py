"""Fetch top-level TikTok comments via public web API (paginated)."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def fetch_comment_page(aweme_id: str, cursor: int = 0, count: int = 50) -> dict:
    q = urllib.parse.urlencode(
        {
            "aid": "1988",
            "aweme_id": aweme_id,
            "count": str(count),
            "cursor": str(cursor),
        }
    )
    url = f"https://www.tiktok.com/api/comment/list/?{q}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Referer": "https://www.tiktok.com/",
            "Accept": "application/json, text/plain, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_all_comments(aweme_id: str, max_comments: int = 600) -> list[dict]:
    out: list[dict] = []
    cursor = 0
    while len(out) < max_comments:
        data = fetch_comment_page(aweme_id, cursor=cursor, count=50)
        comments = data.get("comments") or []
        if not comments:
            break
        for c in comments:
            out.append(
                {
                    "cid": c.get("cid"),
                    "text": (c.get("text") or "").strip(),
                    "digg_count": int(c.get("digg_count") or 0),
                    "reply_comment_total": int(c.get("reply_comment_total") or 0),
                    "create_time": c.get("create_time"),
                }
            )
            if len(out) >= max_comments:
                break
        if not data.get("has_more"):
            break
        cursor = int(data.get("cursor") or 0)
        time.sleep(0.35)
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-existing", action="store_true", help="Skip videos that already have a comments file")
    ap.add_argument("--max-comments", type=int, default=500)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    data_dir = root / "data" / "comments_raw"
    data_dir.mkdir(parents=True, exist_ok=True)
    ids_path = root / "data" / "video_ids.txt"
    if not ids_path.exists():
        raise SystemExit("missing video_ids.txt")
    ids = [l.strip() for l in ids_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"{len(ids)} video IDs loaded")
    for aweme_id in ids:
        dest = data_dir / f"{aweme_id}.json"
        if args.skip_existing and dest.exists():
            print(f"skip existing {aweme_id}")
            continue
        print(f"fetching {aweme_id}", flush=True)
        try:
            comments = fetch_all_comments(aweme_id, max_comments=args.max_comments)
            dest.write_text(json.dumps(comments, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  {len(comments)} comments")
        except Exception as e:
            print(f"  error: {e}")


if __name__ == "__main__":
    main()
