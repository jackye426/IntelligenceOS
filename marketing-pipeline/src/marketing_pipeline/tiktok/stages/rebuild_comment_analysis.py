"""Rebuild labeled comment analysis from comments_raw."""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from pathlib import Path

from marketing_pipeline import config

THEME_PATTERNS: list[tuple[str, list[str]]] = [
    ("advocacy_what_to_ask", [r"\b360\b", r"ask for", r"surgeon", r"refused", r"say no", r"check my"]),
    ("post_op_experience", [r"after surgery", r"months ago", r"worse", r"laparoscopy", r"had mine"]),
    ("imaging_mri", [r"\bmri\b", r"scan", r"pick up", r"imaging"]),
    ("system_frustration", [r"degree in medicine", r"myself\b", r"going in circles", r"not fair", r"ridiculous"]),
    ("humor_reaction", [r"😂|😳|lol|haha|who\?"]),
    ("pouch_anatomy_question", [r"pouch of", r"douglas", r"what is"]),
    ("validation_gratitude", [r"thank", r"needed this", r"so helpful", r"wish i knew"]),
    ("personal_story", [r"\bi\b.*\b(my|me|i'm|i am)\b", r"when i", r"i had"]),
    ("general_question", [r"\?", r"can someone", r"why is", r"what if"]),
]


def label_themes(text: str) -> list[str]:
    t = text.lower()
    hits = []
    for name, pats in THEME_PATTERNS:
        for pat in pats:
            if re.search(pat, t, re.I):
                hits.append(name)
                break
    if not hits:
        hits.append("other_uncategorized")
    return hits


def structured_sentiment(text: str) -> dict:
    t = text.lower()
    stance = "statement"
    if "?" in text or re.match(r"^(what|why|how|can |could |would |is |are )", t):
        stance = "question"
    if re.search(r"\b(i |my |me |i'm|i've|i had|when i)\b", t):
        stance = "personal_story"
    if re.search(r"\b(thank|thanks|love this|helpful|needed)\b", t):
        stance = "agree_validate"

    emotion = "neutral"
    if re.search(r"worse|refused|terrified|angry|frustrat|unfair|😭|💔", t):
        emotion = "distress_frustration"
    elif re.search(r"😂|lol|haha|who\?", t):
        emotion = "humor"
    elif re.search(r"thank|grateful|helpful|amazing", t):
        emotion = "gratitude_hope"

    return {
        "stance": stance,
        "primary_emotion": emotion,
        "toxicity_spam_flag": bool(re.search(r"follow me|check link|http://", t)),
    }


def rebuild_comment_analysis(analysis_dir: Path | None = None) -> dict[str, int]:
    out_dir = analysis_dir or config.ANALYSIS_DIR
    raw_dir = config.COMMENTS_RAW_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries = []
    all_top = []
    labeled_files = 0

    for path in sorted(raw_dir.glob("*.json")):
        video_id = path.stem
        comments = json.loads(path.read_text(encoding="utf-8"))
        if not comments:
            summaries.append(
                {"video_id": video_id, "n_fetched": 0, "themes": {}, "note": "no comments returned"}
            )
            continue

        theme_counts: Counter = Counter()
        stance_counts: Counter = Counter()
        emotion_counts: Counter = Counter()
        labeled = []

        for comment in comments:
            text = comment.get("text") or ""
            themes = label_themes(text)
            for theme in themes:
                theme_counts[theme] += 1
            sent = structured_sentiment(text)
            stance_counts[sent["stance"]] += 1
            emotion_counts[sent["primary_emotion"]] += 1
            labeled.append({**comment, "themes": themes, "sentiment": sent})

        top_by_likes = sorted(comments, key=lambda x: -int(x.get("digg_count") or 0))[:20]
        top_cids = {t.get("cid") for t in top_by_likes}
        pool = [c for c in comments if c.get("cid") not in top_cids]
        rng = random.Random(42)
        sample_n = min(100, len(pool))
        random_stratum = rng.sample(pool, sample_n) if pool and sample_n else []
        rs_themes: Counter = Counter()
        for comment in random_stratum:
            for theme in label_themes(comment.get("text") or ""):
                rs_themes[theme] += 1

        summaries.append(
            {
                "video_id": video_id,
                "n_fetched": len(comments),
                "theme_distribution": dict(theme_counts.most_common()),
                "random_stratum_n": len(random_stratum),
                "random_stratum_theme_distribution": dict(rs_themes.most_common()),
                "stance_distribution": dict(stance_counts),
                "emotion_distribution": dict(emotion_counts),
            }
        )

        all_top.extend(
            [
                {
                    "video_id": video_id,
                    "text": t["text"],
                    "digg_count": t["digg_count"],
                    "themes": label_themes(t["text"]),
                    "sentiment": structured_sentiment(t["text"]),
                }
                for t in top_by_likes[:15]
            ]
        )

        (out_dir / f"comments_labeled_{video_id}.json").write_text(
            json.dumps(labeled, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        labeled_files += 1

    (out_dir / "comment_summary_by_video.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "top_comments_labeled.json").write_text(
        json.dumps(all_top, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"videos": len(summaries), "labeled_files": labeled_files}
