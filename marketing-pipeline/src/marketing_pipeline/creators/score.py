"""Deterministic lane + scores. Missing inputs stay null, never zero."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from marketing_pipeline.creators.good_fit import GOOD_FIT_VERSION, is_good_fit

SCORING_VERSION = "score_v1"

TIER_A = frozenset(
    {"obstetrics_gynaecology", "fertility", "menopause", "endometriosis", "ivf"}
)
TIER_B = frozenset(
    {"dermatology", "colorectal", "general_surgery", "gastroenterology"}
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def derive_eligibility(profile: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    now = now or _now()
    posts_90d = profile.get("posts_90d")
    last_post = _parse_dt(profile.get("last_post_at"))
    active = (
        posts_90d is not None
        and int(posts_90d) >= 3
        and last_post is not None
        and last_post >= now - timedelta(days=120)
    )
    followers = profile.get("follower_count")
    research_eligible = bool(active and followers is not None and int(followers) >= 1000)

    geo = (profile.get("geo_country") or "").upper()
    geo_conf = profile.get("geo_confidence")
    setting = profile.get("practice_setting")
    videos = profile.get("video_count")
    customer_eligible = bool(
        geo == "GB"
        and geo_conf is not None
        and float(geo_conf) >= 0.7
        and setting in {"private", "mixed"}
        and videos is not None
        and int(videos) >= 3
        and not profile.get("do_not_contact")
    )
    return {
        "active": active,
        "research_eligible": research_eligible,
        "customer_eligible": customer_eligible,
    }


def derive_lane(profile: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    reasons: list[str] = []
    if profile.get("review_status") == "confirmed" and profile.get("review_lane_override"):
        return {
            "lane": profile["review_lane_override"],
            "lane_reasons": ["review_lane_override"],
            **derive_eligibility(profile, now=now),
        }

    stage = profile.get("stage")
    conf = profile.get("doctor_confidence")
    if stage in {"excluded", "unavailable"} or not profile.get("is_doctor") or (
        conf is not None and float(conf) < 0.6
    ):
        return {
            "lane": "discard",
            "lane_reasons": ["not_research_or_customer"],
            **derive_eligibility(profile, now=now),
        }

    elig = derive_eligibility(profile, now=now)
    if conf is not None and 0.6 <= float(conf) < 0.8:
        return {"lane": "pending_review", "lane_reasons": ["doctor_confidence_band"], **elig}
    geo_conf = profile.get("geo_confidence")
    if elig["customer_eligible"] is False and geo_conf is not None and 0.5 <= float(geo_conf) < 0.7:
        if elig["research_eligible"]:
            return {"lane": "pending_review", "lane_reasons": ["geo_confidence_band"], **elig}

    if elig["customer_eligible"] and elig["research_eligible"]:
        lane = "both"
    elif elig["customer_eligible"]:
        lane = "customer"
    elif elig["research_eligible"]:
        lane = "research"
    else:
        lane = "discard"
        reasons.append("not_research_or_customer")
    return {"lane": lane, "lane_reasons": reasons or [lane], **elig}


def _points_or_none(points: float | None, weight: int) -> tuple[float | None, int]:
    if points is None:
        return None, 0
    return points, weight


def customer_score(profile: dict[str, Any]) -> dict[str, Any]:
    breakdown: dict[str, Any] = {}
    used = 0
    total = 0.0

    intent = profile.get("growth_intent_level")
    if intent is None:
        breakdown["growth_intent"] = {"points": None, "weight": 30, "rule": "missing"}
    else:
        pts = {0: 0, 1: 10, 2: 20, 3: 30}.get(int(intent), 0)
        breakdown["growth_intent"] = {"points": pts, "weight": 30, "rule": f"intent_{intent}"}
        total += pts
        used += 30

    spec = profile.get("specialty_key")
    setting = profile.get("practice_setting")
    if spec is None and setting is None:
        breakdown["commercial_fit"] = {"points": None, "weight": 25, "rule": "missing"}
    else:
        spec_pts = 15 if spec in TIER_A else 10 if spec in TIER_B else 5
        setting_pts = 10 if setting == "private" else 6 if setting == "mixed" else 0
        pts = spec_pts + setting_pts
        # spec+setting max 25
        pts = min(pts, 25)
        breakdown["commercial_fit"] = {"points": pts, "weight": 25, "rule": f"{spec}/{setting}"}
        total += pts
        used += 25

    followers = profile.get("follower_count")
    if followers is None:
        breakdown["audience_band"] = {"points": None, "weight": 15, "rule": "missing"}
    else:
        n = int(followers)
        if 5_000 <= n <= 100_000:
            pts, rule = 15, "5k_100k"
        elif 2_000 <= n < 5_000 or 100_000 < n <= 250_000:
            pts, rule = 8, "near_band"
        else:
            pts, rule = 3, "outside_band"
        breakdown["audience_band"] = {"points": pts, "weight": 15, "rule": rule}
        total += pts
        used += 15

    saves = profile.get("median_saves_per_1k")
    window = profile.get("recent_window_n")
    if saves is None or window is None or int(window) < 5:
        breakdown["intent_engagement"] = {"points": None, "weight": 15, "rule": "insufficient_saves"}
    else:
        s = float(saves)
        if s >= 15:
            pts = 15
        elif s >= 8:
            pts = 10
        elif s >= 3:
            pts = 5
        else:
            pts = 0
        breakdown["intent_engagement"] = {"points": pts, "weight": 15, "rule": f"saves_{s}"}
        total += pts
        used += 15

    emails = profile.get("bio_emails") or []
    links = profile.get("bio_links") or []
    handles = profile.get("bio_handles") or {}
    classes = {item.get("class") for item in links if isinstance(item, dict)}
    if emails:
        pts, rule = 15, "email"
    elif "own_site" in classes or "booking_platform" in classes:
        pts, rule = 8, "own_or_booking"
    elif handles:
        pts, rule = 4, "social_only"
    else:
        pts, rule = 0, "none"
    breakdown["contactability"] = {"points": pts, "weight": 15, "rule": rule}
    total += pts
    used += 15

    coverage = (used / 100) if used else 0
    scaled = round((total / used) * 100, 2) if used else None
    return {
        "customer_score": scaled,
        "score_coverage": coverage,
        "score_breakdown": breakdown,
        "scoring_version": SCORING_VERSION,
    }


def _percentile(value: float | None, peers: list[float]) -> float | None:
    if value is None or len(peers) < 30:
        return None
    ordered = sorted(peers)
    n_le = sum(1 for p in ordered if p <= value)
    return n_le / len(ordered)


def research_score(
    profile: dict[str, Any],
    *,
    band_views_to_followers: list[float] | None = None,
    band_saves: list[float] | None = None,
) -> dict[str, Any]:
    breakdown: dict[str, Any] = {}
    used = 0
    total = 0.0

    posts_30d = profile.get("posts_30d")
    if posts_30d is None:
        breakdown["cadence"] = {"points": None, "weight": 20, "rule": "missing"}
    else:
        n = int(posts_30d)
        pts = 20 if n >= 12 else 14 if n >= 6 else 8 if n >= 3 else 3 if n >= 1 else 0
        breakdown["cadence"] = {"points": pts, "weight": 20, "rule": f"posts_30d_{n}"}
        total += pts
        used += 20

    pct = _percentile(profile.get("views_to_followers_median"), band_views_to_followers or [])
    if pct is None:
        breakdown["reach_efficiency"] = {"points": None, "weight": 25, "rule": "band_n<30"}
    else:
        pts = round(pct * 25, 2)
        breakdown["reach_efficiency"] = {"points": pts, "weight": 25, "rule": "percentile"}
        total += pts
        used += 25

    save_pct = _percentile(profile.get("median_saves_per_1k"), band_saves or [])
    if save_pct is None:
        breakdown["save_intent"] = {"points": None, "weight": 20, "rule": "band_n<30"}
    else:
        pts = round(save_pct * 20, 2)
        breakdown["save_intent"] = {"points": pts, "weight": 20, "rule": "percentile"}
        total += pts
        used += 20

    weeks = profile.get("weeks_active_of_last_8")
    if weeks is None:
        breakdown["consistency"] = {"points": None, "weight": 10, "rule": "missing"}
    else:
        pts = (int(weeks) / 8) * 10
        breakdown["consistency"] = {"points": pts, "weight": 10, "rule": f"weeks_{weeks}"}
        total += pts
        used += 10

    formats = profile.get("content_formats") or []
    mix = profile.get("format_mix") or {}
    format_counts = mix if isinstance(mix, dict) else {}
    if any(int(v) >= 3 for v in format_counts.values()):
        pts, rule = 15, "format_ge_3"
    elif profile.get("series_markers"):
        pts, rule = 10, "series_marker"
    elif formats:
        pts, rule = 0, "formats_present_no_repeat"
    else:
        pts, rule = None, "missing"
    if pts is None:
        breakdown["format_signal"] = {"points": None, "weight": 15, "rule": rule}
    else:
        breakdown["format_signal"] = {"points": pts, "weight": 15, "rule": rule}
        total += pts
        used += 15

    cta = set(profile.get("cta_types") or [])
    owned = {"newsletter", "podcast_or_book", "course", "book_consult"}
    if not cta:
        breakdown["funnel_signal"] = {"points": None, "weight": 10, "rule": "missing"}
    elif cta & owned:
        breakdown["funnel_signal"] = {"points": 10, "weight": 10, "rule": "owned_next_step"}
        total += 10
        used += 10
    elif "link_in_bio" in cta:
        breakdown["funnel_signal"] = {"points": 5, "weight": 10, "rule": "link_in_bio"}
        total += 5
        used += 10
    else:
        breakdown["funnel_signal"] = {"points": 0, "weight": 10, "rule": "other_cta"}
        total += 0
        used += 10

    coverage = used / 100 if used else 0
    scaled = round((total / used) * 100, 2) if used else None
    return {
        "research_score": scaled,
        "score_coverage": coverage,
        "score_breakdown": breakdown,
        "scoring_version": SCORING_VERSION,
    }


def score_profile(
    profile: dict[str, Any],
    *,
    band_views_to_followers: list[float] | None = None,
    band_saves: list[float] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    lane = derive_lane(profile, now=now)
    cust = customer_score(profile)
    research = research_score(
        profile,
        band_views_to_followers=band_views_to_followers,
        band_saves=band_saves,
    )
    merged = {
        **profile,
        **lane,
        "customer_score": cust["customer_score"],
        "research_score": research["research_score"],
        "score_breakdown": {"customer": cust["score_breakdown"], "research": research["score_breakdown"]},
        "score_coverage": {
            "customer": cust["score_coverage"],
            "research": research["score_coverage"],
        },
        "scoring_version": SCORING_VERSION,
    }
    merged["good_fit"] = is_good_fit(merged)
    merged["good_fit_version"] = GOOD_FIT_VERSION
    merged["stage"] = "scored" if profile.get("stage") in {"classified", "scored", "hydrated"} else profile.get("stage")
    return merged


def follower_band(followers: int | None) -> str:
    if followers is None:
        return "unknown"
    n = int(followers)
    if n < 2_000:
        return "lt_2k"
    if n < 5_000:
        return "2k_5k"
    if n <= 100_000:
        return "5k_100k"
    if n <= 250_000:
        return "100k_250k"
    return "gt_250k"
