#!/usr/bin/env python3
"""Find likely A/B pairs by comparing TikTok transcripts and hooks."""

from __future__ import annotations

import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "marketing-pipeline" / "src"))

from marketing_pipeline.tiktok.orchestrator import build_dataset  # noqa: E402
from marketing_pipeline.tiktok.stages.detect_ab_pairs import _body_after_hook  # noqa: E402


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def hook_text(rec) -> str:
    h = rec.hook
    return (h.onscreen_hook or h.spoken_hook or h.caption_hook or "").strip()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ds = build_dataset()

    rows = []
    for vid, rec in ds.videos.items():
        transcript = rec.transcript.full_text or ""
        rows.append(
            {
                "vid": vid,
                "views": rec.post.metrics.views or 0,
                "saves_per_1k": rec.post.metrics.saves_per_1k_views or 0,
                "hook": hook_text(rec),
                "hook_src": rec.hook.hook_source,
                "body": _body_after_hook(transcript),
                "full": transcript.lower(),
                "opening": transcript.strip()[:250].lower(),
                "caption": (rec.post.caption or "").split("\n")[0][:120],
                "posted_at": rec.post.posted_at,
            }
        )

    candidates: list[dict] = []
    for i, a in enumerate(rows):
        for b in rows[i + 1 :]:
            body_sim = similarity(a["body"], b["body"])
            full_sim = similarity(a["full"], b["full"])
            open_sim = similarity(a["opening"], b["opening"])
            cap_sim = similarity(a["caption"].lower(), b["caption"].lower())
            hook_sim = similarity(a["hook"].lower(), b["hook"].lower())

            hooks_differ = hook_sim < 0.88 and a["hook"] and b["hook"]
            if not hooks_differ:
                continue

            # Relaxed gates — user says many pairs exist
            body_ok = body_sim >= 0.32 and min(len(a["body"]), len(b["body"])) >= 60
            full_ok = full_sim >= 0.38 and min(len(a["full"]), len(b["full"])) >= 80
            open_ok = open_sim >= 0.58
            cap_ok = cap_sim >= 0.72 and hooks_differ

            if not (body_ok or full_ok or open_ok or cap_ok):
                continue

            score = max(body_sim, full_sim, open_sim, cap_sim * 0.95)
            candidates.append(
                {
                    "score": round(score, 3),
                    "body_sim": round(body_sim, 3),
                    "full_sim": round(full_sim, 3),
                    "open_sim": round(open_sim, 3),
                    "cap_sim": round(cap_sim, 3),
                    "hook_sim": round(hook_sim, 3),
                    "basis": (
                        "body"
                        if body_ok and body_sim >= max(full_sim, open_sim, cap_sim)
                        else "full"
                        if full_ok and full_sim >= max(body_sim, open_sim, cap_sim)
                        else "opening"
                        if open_ok
                        else "caption"
                    ),
                    "a": a,
                    "b": b,
                }
            )

    candidates.sort(key=lambda x: (-x["score"], -x["body_sim"]))

    print(f"Videos analyzed: {len(rows)}")
    print(f"Candidate pairs: {len(candidates)}\n")

    for c in candidates:
        a, b = c["a"], c["b"]
        print("=" * 72)
        print(
            f"score={c['score']} basis={c['basis']} "
            f"body={c['body_sim']} full={c['full_sim']} open={c['open_sim']} "
            f"cap={c['cap_sim']} hook_diff={c['hook_sim']}"
        )
        print(f"  A views={a['views']:,} saves/1k={a['saves_per_1k']} {a['vid']}")
        print(f"     hook [{a['hook_src']}]: {a['hook'][:100]}")
        print(f"  B views={b['views']:,} saves/1k={b['saves_per_1k']} {b['vid']}")
        print(f"     hook [{b['hook_src']}]: {b['hook'][:100]}")
        print(f"  A open: {a['opening'][:120]}...")
        print(f"  B open: {b['opening'][:120]}...")

    # Cluster by connected components for multi-arm groups
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for c in candidates:
        if c["score"] >= 0.40 or c["body_sim"] >= 0.35:
            union(c["a"]["vid"], c["b"]["vid"])

    clusters: dict[str, list[str]] = {}
    for row in rows:
        vid = row["vid"]
        root = find(vid)
        clusters.setdefault(root, []).append(vid)

    multi = [sorted(vids) for vids in clusters.values() if len(vids) >= 2]
    multi.sort(key=len, reverse=True)

    print("\n" + "=" * 72)
    print(f"CLUSTERS (connected pairs, score>=0.40 or body>=0.35): {len(multi)}")
    for vids in multi:
        print(f"\n--- cluster ({len(vids)} videos) ---")
        for vid in vids:
            row = next(r for r in rows if r["vid"] == vid)
            print(f"  {row['views']:>7} {vid} | {row['hook'][:90]}")


if __name__ == "__main__":
    main()
