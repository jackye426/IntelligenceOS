"""Load TikTok strategy brief and insight state from Supabase."""

from __future__ import annotations

from typing import Any

from common.supabase_client import get_client

STRATEGY_PLATFORM = "tiktok_meta"
STRATEGY_POST_ID = "strategy_state"


def fetch_strategy_row() -> dict[str, Any] | None:
    rows = (
        get_client()
        .table("content_posts")
        .select("metadata, posted_at")
        .eq("platform", STRATEGY_PLATFORM)
        .eq("platform_post_id", STRATEGY_POST_ID)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def fetch_strategy_brief() -> dict[str, Any]:
    row = fetch_strategy_row()
    if not row:
        return {
            "ok": False,
            "error": "Strategy brief not synced. Run: tiktok export && tiktok sync-supabase",
        }
    meta = row.get("metadata") or {}
    brief = meta.get("strategy_brief") or {}
    brief.setdefault("meta", {})
    return {"ok": True, "brief": brief, "updated_at": meta.get("updated_at")}


def save_strategy_metadata(meta: dict[str, Any]) -> None:
    client = get_client()
    existing = (
        client.table("content_posts")
        .select("id")
        .eq("platform", STRATEGY_PLATFORM)
        .eq("platform_post_id", STRATEGY_POST_ID)
        .limit(1)
        .execute()
    )
    if existing.data:
        client.table("content_posts").update({"metadata": meta}).eq(
            "id", existing.data[0]["id"]
        ).execute()
    else:
        client.table("content_posts").insert(
            {
                "platform": STRATEGY_PLATFORM,
                "platform_post_id": STRATEGY_POST_ID,
                "title": "TikTok strategy state",
                "metadata": meta,
            }
        ).execute()


def brief_excerpt_for_prompt(*, max_chars: int = 6000) -> str:
    data = fetch_strategy_brief()
    if not data.get("ok"):
        return data.get("error") or "Strategy brief unavailable."
    brief = data["brief"]
    parts = [
        "## Constitution (excerpt)\n" + (brief.get("1_constitution") or "")[:2500],
        "## Approved insights\n" + str(brief.get("3_approved_insights") or [])[:2000],
        "## Anti-patterns\n" + "\n".join(f"- {x}" for x in brief.get("5_anti_patterns") or []),
        "## Reference set\n" + str(brief.get("reference_set") or [])[:1500],
    ]
    text = "\n\n".join(parts)
    return text[:max_chars]
