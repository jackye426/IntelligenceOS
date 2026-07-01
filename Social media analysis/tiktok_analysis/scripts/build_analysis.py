"""Build feature matrix, comment themes, structured sentiment labels."""
from __future__ import annotations

import json
import random
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "analysis"
OUT.mkdir(parents=True, exist_ok=True)

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
        for p in pats:
            if re.search(p, t, re.I):
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

    return {"stance": stance, "primary_emotion": emotion, "toxicity_spam_flag": bool(re.search(r"follow me|check link|http://", t))}


def first_segment_hook(transcript_lines: str) -> tuple[str, str]:
    for line in transcript_lines.splitlines():
        m = re.match(r"\[([\d.]+)-([\d.]+)\]\s*(.+)", line.strip())
        if m:
            start = float(m.group(1))
            text = (m.group(3) or "").strip()
            if len(text) < 3 or text in {".", ".."}:
                continue
            if start <= 3.0 or (start <= 8.0 and len(text) > 10):
                if start <= 3.0:
                    kind = "opening_under_3s"
                else:
                    kind = "early_hook_3_8s"
                return text, kind
    return "", "unknown"


def load_transcript(aid: str) -> str:
    p = DATA / "transcripts" / f"{aid}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def rubric_from_content(aid: str, label: str, desc: str, transcript: str) -> dict:
    opening, hook_window = first_segment_hook(transcript)
    if not opening or len(opening) < 8:
        opening = (desc.split(".")[0] if desc else "").strip()[:220]
        hook_window = "description_fallback_no_clear_speech"
    full = (desc + " " + transcript).lower()

    info_arch = "expert_monologue"
    if "responding to a question" in desc.lower():
        info_arch = "faq_response"
    if "part two" in desc.lower():
        info_arch = "sequel_explainer"
    if "how did the" in desc.lower() or "how does that feel" in transcript.lower():
        info_arch = "interview_qa"

    specificity = 3
    if aid == "7630900114982210838":
        specificity = 5
    elif aid == "7631220659770690818":
        specificity = 4
    elif aid in ("7633862545228434710", "7634274846117104918"):
        specificity = 4
    elif aid in ("7635716747869424918", "7636091017875197207"):
        specificity = 3

    tone = []
    if re.search(r"terrified|heartbreak|not alone|community", full):
        tone.append("validation_vulnerability")
    if re.search(r"rubbish|miss it|not enough|8 minutes", full):
        tone.append("system_critique")
    if re.search(r"skimming|plaster|wall", full):
        tone.append("analogy_teach")
    if re.search(r"mind-blowing|everyone should ask", desc.lower()):
        tone.append("urgency_advocacy")

    cta = "link_in_bio_booking" if "bio" in desc.lower() or "zoom" in desc.lower() else "question_prompt"
    if "whatsapp" in desc.lower():
        cta = "whatsapp_message"

    hook_type = "bold_claim_procedure"
    if "excision" in opening.lower():
        hook_type = "rule_meme_style"
    if "9 years" in opening.lower() or "9 year" in desc.lower():
        hook_type = "stat_shock"
    if "8 minutes" in opening.lower() or "8 minute" in (desc or "").lower():
        hook_type = "time_constraint_gp"
    if "30,000" in transcript or "30k" in desc.lower():
        hook_type = "community_scale_question"
    if "endo belly" in (desc or "").lower():
        hook_type = "symptom_identity_validation"

    return {
        "video_id": aid,
        "short_label": label,
        "hook_verbatim_opening": opening[:220],
        "hook_window": hook_window,
        "hook_classification": hook_type,
        "promise_first_10s": opening[:300],
        "info_architecture": info_arch,
        "specificity_score_1_5": specificity,
        "tone_tags": tone,
        "cta_type": cta,
        "topic_overlap_note": {
            "7630900114982210838": "Unique: intra-op 360 checklist + pouch of Douglas demo; high surgical literacy.",
            "7631220659770690818": "Overlaps viral clip (excision); shorter analogy-led.",
            "7633862545228434710": "Overlaps 7634274846117104918 (9-year delay series).",
            "7634274846117104918": "Part 2 same arc as 7633862545228434710.",
            "7631307430890048790": "Intro carousel; less procedural detail.",
            "7635716747869424918": "Service-led (WhatsApp) vs Liz clinical series.",
            "7636091017875197207": "Symptom identity (endo belly); longform.",
            "7629626326927805718": "Creator story + community; not Liz clinical.",
        }.get(aid, ""),
    }


def load_all_metrics() -> list[dict]:
    """Merge metrics_refresh.json (8 deep entries) with the full catalog JSONs."""
    by_id: dict[str, dict] = {}
    # Full catalog: view counts + dates for every video
    for p in sorted(DATA.glob("docmap_catalog_since_*.json")):
        for e in json.loads(p.read_text(encoding="utf-8")):
            vid = e.get("video_id", "")
            if vid and vid not in by_id:
                by_id[vid] = {
                    "video_id": vid,
                    "label": (e.get("title") or e.get("description") or "")[:60],
                    "description": e.get("description") or "",
                    "view_count": int(e.get("view_count") or 0),
                    "like_count": int(e.get("like_count") or 0),
                    "comment_count": int(e.get("comment_count") or 0),
                    "share_count": int(e.get("share_count") or 0),
                    "save_count": int(e.get("save_count") or 0),
                    "like_per_1k_views": None,
                    "share_per_1k_views": None,
                    "save_per_1k_views": None,
                }
    # Overlay the richer metrics_refresh.json entries
    if (DATA / "metrics_refresh.json").exists():
        for m in json.loads((DATA / "metrics_refresh.json").read_text(encoding="utf-8")):
            vid = m.get("video_id", "")
            if vid:
                by_id[vid] = m
    # Compute per-1k ratios where missing
    for m in by_id.values():
        vc = m.get("view_count") or 0
        for key, src in [("like_per_1k_views", "like_count"), ("share_per_1k_views", "share_count"), ("save_per_1k_views", "save_count")]:
            if m.get(key) is None and vc:
                m[key] = round(1000 * (m.get(src) or 0) / vc, 4)
    return sorted(by_id.values(), key=lambda x: x.get("view_count") or 0, reverse=True)


def main():
    metrics = load_all_metrics()

    matrix = []
    for m in metrics:
        aid = m["video_id"]
        tr = load_transcript(aid)
        matrix.append(rubric_from_content(aid, m.get("label") or aid, m.get("description") or "", tr))

    (OUT / "feature_matrix.json").write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    comment_summaries = []
    all_top = []

    raw_dir = DATA / "comments_raw"
    for path in sorted(raw_dir.glob("*.json")):
        aid = path.stem
        comments = json.loads(path.read_text(encoding="utf-8"))
        if not comments:
            comment_summaries.append({"video_id": aid, "n_fetched": 0, "themes": {}, "note": "no comments returned"})
            continue

        theme_counts: Counter = Counter()
        stance_counts: Counter = Counter()
        emotion_counts: Counter = Counter()
        labeled = []

        for c in comments:
            text = c.get("text") or ""
            themes = label_themes(text)
            for th in themes:
                theme_counts[th] += 1
            sent = structured_sentiment(text)
            stance_counts[sent["stance"]] += 1
            emotion_counts[sent["primary_emotion"]] += 1
            labeled.append({**c, "themes": themes, "sentiment": sent})

        top_by_likes = sorted(comments, key=lambda x: -x.get("digg_count", 0))[:20]
        top_cids = {t.get("cid") for t in top_by_likes}
        pool = [c for c in comments if c.get("cid") not in top_cids]
        rng = random.Random(42)
        k = min(100, len(pool))
        random_stratum = rng.sample(pool, k) if pool and k else []
        rs_themes: Counter = Counter()
        for c in random_stratum:
            for th in label_themes(c.get("text") or ""):
                rs_themes[th] += 1

        comment_summaries.append(
            {
                "video_id": aid,
                "n_fetched": len(comments),
                "theme_distribution": dict(theme_counts.most_common()),
                "random_stratum_n": len(random_stratum),
                "random_stratum_theme_distribution": dict(rs_themes.most_common()),
                "stance_distribution": dict(stance_counts),
                "emotion_distribution": dict(emotion_counts),
                "top_by_likes_preview": [
                    {"text": t["text"][:200], "digg_count": t["digg_count"], "themes": label_themes(t["text"])}
                    for t in top_by_likes[:8]
                ],
            }
        )

        all_top.extend(
            [
                {
                    "video_id": aid,
                    "text": t["text"],
                    "digg_count": t["digg_count"],
                    "themes": label_themes(t["text"]),
                    "sentiment": structured_sentiment(t["text"]),
                }
                for t in top_by_likes[:15]
            ]
        )

        (OUT / f"comments_labeled_{aid}.json").write_text(
            json.dumps(labeled, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    (OUT / "comment_summary_by_video.json").write_text(
        json.dumps(comment_summaries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "top_comments_labeled.json").write_text(
        json.dumps(all_top, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Rank labels vs cohort median views
    views_list = [m["view_count"] for m in metrics]
    median_v = sorted(views_list)[len(views_list) // 2]

    ranked = []
    for m in sorted(metrics, key=lambda x: x["view_count"], reverse=True):
        vc = m["view_count"]
        tier = "outperform" if vc >= median_v * 3 else ("in_line" if vc >= median_v * 0.5 else "underperform")
        ranked.append(
            {
                "video_id": m["video_id"],
                "label": m.get("label") or aid,
                "views": vc,
                "tier_vs_cohort": tier,
                "share_per_1k": m["share_per_1k_views"],
                "save_per_1k": m["save_per_1k_views"],
            }
        )

    (OUT / "performance_tiers.json").write_text(
        json.dumps(ranked, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("wrote analysis/*.json")


if __name__ == "__main__":
    main()
