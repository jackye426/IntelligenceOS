"""Auto-draft evidence playbook from dataset metrics."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from marketing_pipeline import config
from marketing_pipeline.tiktok.models import TikTokMarketingDataset


def _saves_per_1k(metrics: dict) -> float:
    if metrics.get("saves_per_1k_views") is not None:
        return float(metrics["saves_per_1k_views"])
    views = metrics.get("views") or 0
    saves = metrics.get("saves") or 0
    return round((saves / views) * 1000, 2) if views else 0.0


def draft_evidence_playbook(dataset: TikTokMarketingDataset) -> Path:
    drafts_dir = config.PLAYBOOKS_DIR / "evidence" / "_drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    out = drafts_dir / f"recipe-{month}.md"

    ranked = sorted(
        dataset.videos.values(),
        key=lambda r: _saves_per_1k(r.post.metrics.model_dump()),
        reverse=True,
    )

    lines = [
        "---",
        "status: draft",
        f"as_of: {datetime.now(timezone.utc).date().isoformat()}",
        f"video_count: {len(dataset.videos)}",
        "note: Auto-generated — review before approving",
        "---",
        "",
        f"# TikTok evidence draft ({month})",
        "",
        "## Top posts by saves per 1k views",
        "",
    ]

    for record in ranked[:5]:
        metrics = record.post.metrics.model_dump()
        hook = record.hook.onscreen_hook or record.hook.spoken_hook or record.hook.caption_hook or ""
        lines.append(
            f"- **{record.post.video_id}** — saves/1k={_saves_per_1k(metrics)}, "
            f"views={metrics.get('views')}, hook: {hook[:100]}"
        )

    lines.extend(["", "## A/B pairs", ""])
    for pair in dataset.ab_pairs[:10]:
        lines.append(
            f"- `{pair.pair_id}`: {pair.video_a} vs {pair.video_b} — {pair.learning or pair.similarity_basis}"
        )

    lines.extend(["", "## OCR vs spoken hook notes", ""])
    ocr_count = sum(1 for r in dataset.videos.values() if r.hook.onscreen_hook)
    lines.append(f"- Videos with on-screen hook: {ocr_count}/{len(dataset.videos)}")

    out.write_text("\n".join(lines), encoding="utf-8")
    return out
