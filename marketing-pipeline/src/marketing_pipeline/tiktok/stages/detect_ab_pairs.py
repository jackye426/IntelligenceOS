"""Detect likely A/B test pairs from transcript/caption similarity."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from marketing_pipeline.tiktok.models import (
    PerformanceDifference,
    TikTokABPair,
    TikTokMarketingDataset,
    TikTokVideoRecord,
)

from marketing_pipeline.tiktok.stages.ab_pair_registry import load_registry_pairs


def _body_after_hook(transcript: str | None) -> str:
    if not transcript:
        return ""
    text = transcript.strip()
    match = re.search(r"[.!?](?:\s|$)", text)
    if match:
        return text[match.end() :].strip().lower()
    return text.lower()


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def detect_ab_pairs(dataset: TikTokMarketingDataset) -> list[TikTokABPair]:
    pairs: list[TikTokABPair] = []
    seen: set[tuple[str, str]] = set()

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

        hook_a = (
            rec_a.hook.onscreen_hook
            or rec_a.hook.spoken_hook
            or rec_a.hook.caption_hook
            or ""
        )
        hook_b = (
            rec_b.hook.onscreen_hook
            or rec_b.hook.spoken_hook
            or rec_b.hook.caption_hook
            or ""
        )
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

    for entry in load_registry_pairs():
        pair_id = str(entry.get("pair_id") or "")
        ids = [str(v) for v in entry.get("video_ids") or []]
        learning = entry.get("learning") or entry.get("label")
        present = [vid for vid in ids if vid in dataset.videos]
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                add_pair(pair_id, present[i], present[j], "registry", learning=learning)

    video_ids = list(dataset.videos.keys())
    for i, vid_a in enumerate(video_ids):
        rec_a: TikTokVideoRecord = dataset.videos[vid_a]
        body_a = _body_after_hook(rec_a.transcript.full_text)
        if len(body_a) < 80:
            continue
        for vid_b in video_ids[i + 1 :]:
            rec_b = dataset.videos[vid_b]
            body_b = _body_after_hook(rec_b.transcript.full_text)
            if _similarity(body_a, body_b) < 0.72:
                continue
            hook_a = (
                rec_a.hook.onscreen_hook
                or rec_a.hook.spoken_hook
                or ""
            )
            hook_b = (
                rec_b.hook.onscreen_hook
                or rec_b.hook.spoken_hook
                or ""
            )
            if _similarity(hook_a.lower(), hook_b.lower()) > 0.85:
                continue
            pair_id = f"auto-{vid_a[:8]}-{vid_b[:8]}"
            add_pair(
                pair_id,
                vid_a,
                vid_b,
                "transcript_body_match",
                learning="Same body content with different opening hooks",
            )

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
