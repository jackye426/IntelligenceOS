"""Detect carousel / music-only transcripts.

Most rules here are generic (empty, too short, music-only, outro boilerplate).
One is not: the topic gate below discards a transcript whose caption looks
DocMap-shaped but whose speech does not. That is relevance filtering for one
account's subject matter, and applying it to another creator silently throws
away good transcripts — it discarded roughly half of an early peer ingest,
including plain talking-head videos. It is therefore DocMap-only.
"""

from __future__ import annotations

import re

from marketing_pipeline import config

MEDICAL_TOPIC_HINT = re.compile(
    r"endo|endometriosis|period|pain|symptom|diagnos|women|girl|school|patient|gp|doctor|"
    r"nurse|fatigue|cycle|laparoscopy|uterus|gyn|pelvic|hormone|womb|surgery|clinic|treatment|"
    r"mri|ovaries|bowel|appointment|specialist",
    re.I,
)


def is_garbage_transcript(
    full_text: str | None,
    *,
    caption_hint: str | None = None,
    apply_topic_gate: bool | None = None,
) -> bool:
    """True when a transcript carries no usable speech.

    `apply_topic_gate` controls only the DocMap subject-matter rule; it defaults
    to off for peer accounts. Every other rule is generic and always applies.
    """
    if apply_topic_gate is None:
        apply_topic_gate = not config.is_peer_account()
    t = (full_text or "").strip()
    if not t:
        return True
    tl = t.lower()
    if len(t) < 18:
        return True
    words = tl.split()
    if len(words) <= 2 and len(t) < 40:
        return True
    if words and len(set(words)) == 1 and words[0] == "music":
        return True
    if re.fullmatch(r"(music\s*)+", tl):
        return True
    words_clean = [w.strip(".,!?") for w in tl.split() if w.strip(".,!?")]
    if len(words_clean) >= 3:
        noise_tokens = {"music", "you", "yeah", "uh", "um"}
        noise_hits = sum(1 for w in words_clean if w in noise_tokens)
        if noise_hits / len(words_clean) >= 0.6:
            return True
    if "♪" in t or "music playing" in tl or "piano play" in tl:
        return True
    if re.search(
        r"today'?s video|see you (guys )?in the next|peace out|thanks for watching",
        tl,
    ):
        return True
    if apply_topic_gate and caption_hint and len(t) < 600:
        if MEDICAL_TOPIC_HINT.search(caption_hint) and not MEDICAL_TOPIC_HINT.search(t):
            return True
    return False
