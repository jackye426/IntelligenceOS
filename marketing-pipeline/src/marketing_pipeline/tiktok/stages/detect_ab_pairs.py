"""Detect likely A/B test pairs from registry + Whisper segment alignment."""

from __future__ import annotations

from itertools import combinations

from marketing_pipeline.tiktok.models import (
    PerformanceDifference,
    TikTokABPair,
    TikTokMarketingDataset,
    TikTokVideoRecord,
)

from marketing_pipeline.tiktok.stages.ab_pair_registry import load_registry_pairs
from marketing_pipeline.tiktok.stages.segment_align import (
    HOOK_SIM_MAX,
    SEGMENT_ALIGN_MIN,
    ab_posts_on_different_days,
    load_whisper_segments,
    segment_align_score,
    text_similarity,
)


def _hook_text(rec: TikTokVideoRecord) -> str:
    h = rec.hook
    return (h.onscreen_hook or h.spoken_hook or h.caption_hook or "").strip()


def detect_ab_pairs(dataset: TikTokMarketingDataset) -> list[TikTokABPair]:
    pairs: list[TikTokABPair] = []
    seen: set[tuple[str, str]] = set()
    paired_videos: set[str] = set()

    def add_pair(
        pair_id: str,
        video_a: str,
        video_b: str,
        basis: str,
        learning: str | None = None,
    ) -> None:
        key = tuple(sorted([video_a, video_b]))
        if key in seen:
            return
        seen.add(key)

        rec_a = dataset.videos.get(video_a)
        rec_b = dataset.videos.get(video_b)
        if not rec_a or not rec_b:
            return

        views_a = rec_a.post.metrics.views or 0
        views_b = rec_b.post.metrics.views or 0
        saves_a = rec_a.post.metrics.saves_per_1k_views
        saves_b = rec_b.post.metrics.saves_per_1k_views
        perf = PerformanceDifference(
            views_delta=views_a - views_b,
            likes_delta=(rec_a.post.metrics.likes or 0) - (rec_b.post.metrics.likes or 0),
        )
        if saves_a is not None and saves_b is not None:
            perf.saves_per_1k_delta = round(saves_a - saves_b, 2)

        hook_a = _hook_text(rec_a)
        hook_b = _hook_text(rec_b)
        hook_diff = f"A: {hook_a[:120]} | B: {hook_b[:120]}"

        pairs.append(
            TikTokABPair(
                pair_id=pair_id,
                video_a=video_a,
                video_b=video_b,
                similarity_basis=basis,
                hook_difference=hook_diff,
                performance_difference=perf,
                learning=learning,
            )
        )
        paired_videos.add(video_a)
        paired_videos.add(video_b)

    for entry in load_registry_pairs():
        pair_id = str(entry.get("pair_id") or "")
        ids = [str(v) for v in entry.get("video_ids") or []]
        learning = entry.get("learning") or entry.get("label")
        present = [vid for vid in ids if vid in dataset.videos]
        if len(present) < 2:
            continue
        for video_a, video_b in combinations(present, 2):
            add_pair(pair_id, video_a, video_b, "registry", learning=learning)

    # Auto-suggest: one partner per video max; best segment alignment wins.
    video_ids = [v for v in dataset.videos if v not in paired_videos]
    candidates: list[tuple[float, str, str]] = []

    for i, vid_a in enumerate(video_ids):
        rec_a: TikTokVideoRecord = dataset.videos[vid_a]
        segs_a = load_whisper_segments(vid_a)
        if not segs_a:
            continue
        hook_a = _hook_text(rec_a)
        if not hook_a:
            continue

        for vid_b in video_ids[i + 1 :]:
            rec_b = dataset.videos[vid_b]
            if not ab_posts_on_different_days(rec_a.post.posted_at, rec_b.post.posted_at):
                continue

            hook_b = _hook_text(rec_b)
            if not hook_b:
                continue
            if text_similarity(hook_a, hook_b) > HOOK_SIM_MAX:
                continue

            segs_b = load_whisper_segments(vid_b)
            if not segs_b:
                continue

            align = segment_align_score(segs_a, segs_b)
            if align < SEGMENT_ALIGN_MIN:
                continue

            candidates.append((align, vid_a, vid_b))

    candidates.sort(reverse=True)
    used: set[str] = set(paired_videos)
    for align, vid_a, vid_b in candidates:
        if vid_a in used or vid_b in used:
            continue
        pair_id = f"auto-seg-{vid_a[:8]}-{vid_b[:8]}"
        add_pair(
            pair_id,
            vid_a,
            vid_b,
            f"segment_align:{align:.2f}",
            learning="Same underlying audio with different hook packaging",
        )
        used.add(vid_a)
        used.add(vid_b)

    return pairs


def attach_pairs_to_videos(
    dataset: TikTokMarketingDataset, pairs: list[TikTokABPair]
) -> None:
    for pair in pairs:
        for role, vid, partner in [
            ("video_a", pair.video_a, pair.video_b),
            ("video_b", pair.video_b, pair.video_a),
        ]:
            if vid not in dataset.videos:
                continue
            dataset.videos[vid].ab_pairs.append(
                {
                    "pair_id": pair.pair_id,
                    "partner_video_id": partner,
                    "role": role,
                    "learning": pair.learning,
                    "performance_difference": pair.performance_difference.model_dump(),
                }
            )
