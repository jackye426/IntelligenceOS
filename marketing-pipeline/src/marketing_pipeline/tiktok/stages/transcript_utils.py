"""Detect carousel / music-only transcripts."""

from __future__ import annotations

import re

MEDICAL_TOPIC_HINT = re.compile(
    r"endo|endometriosis|period|pain|symptom|diagnos|women|girl|school|patient|gp|doctor|"
    r"nurse|fatigue|cycle|laparoscopy|uterus|gyn|pelvic|hormone|womb|surgery|clinic|treatment|"
    r"mri|ovaries|bowel|appointment|specialist",
    re.I,
)


def is_garbage_transcript(full_text: str | None, *, caption_hint: str | None = None) -> bool:
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
    if caption_hint and len(t) < 600:
        if MEDICAL_TOPIC_HINT.search(caption_hint) and not MEDICAL_TOPIC_HINT.search(t):
            return True
    return False
