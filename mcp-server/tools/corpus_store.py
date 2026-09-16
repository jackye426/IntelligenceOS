"""In-process / Supabase access for creator_* tables used by MCP corpus tools.

MCP never imports marketing_pipeline.creators.store so a corpus session cannot
load tiktok.sync or call activate_account.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any

from common.supabase_client import get_client

TABLES = (
    "creator_seeds",
    "creator_discovery_hits",
    "creator_profiles",
    "creator_profile_snapshots",
    "creator_videos",
    "creator_insight_cards",
    "creator_specialty_stats",
    "creator_peer_briefs",
    "creator_deep_jobs",
    "creator_deep_job_items",
    "creator_links",
    "creator_crawl_runs",
)

LEAN_FIELDS = (
    "id",
    "handle",
    "profile_url",
    "nickname",
    "specialty_key",
    "doctor_role",
    "geo_country",
    "follower_count",
    "posts_30d",
    "median_views",
    "median_saves_per_1k",
    "median_shares_per_1k",
    "median_engagement_rate",
    "private_practice",
    "growth_intent_level",
    "positioning_line",
    "lane",
    "customer_score",
    "research_score",
    "score_coverage",
    "review_status",
    "promoted",
    "good_fit",
    "deep_status",
    "last_post_at",
    "scored_at",
)

PRIMARY_KEYS = {
    "creator_videos": "video_id",
    "creator_specialty_stats": "specialty_key",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _pk(table: str) -> str:
    return PRIMARY_KEYS.get(table, "id")


def lean_row(profile: dict[str, Any]) -> dict[str, Any]:
    setting = (profile.get("practice_setting") or "").lower()
    row = {key: profile.get(key) for key in LEAN_FIELDS}
    row["private_practice"] = setting in {"private", "mixed"}
    row["promoted"] = profile.get("promoted_at") is not None
    row["id"] = profile.get("id")
    return row


class MemoryCorpus:
    """Test double. Same table names as sql/014."""

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {name: [] for name in TABLES}

    def insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        item = copy.deepcopy(row)
        pk = _pk(table)
        item.setdefault(pk, str(uuid.uuid4()) if pk == "id" else item.get(pk))
        item.setdefault("created_at", _now())
        item.setdefault("updated_at", _now())
        self.tables.setdefault(table, []).append(item)
        return copy.deepcopy(item)

    def upsert(self, table: str, row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
        item = copy.deepcopy(row)
        item.setdefault("updated_at", _now())
        rows = self.tables.setdefault(table, [])
        for i, existing in enumerate(rows):
            if all(existing.get(k) == item.get(k) for k in keys):
                merged = {**existing, **item}
                merged["updated_at"] = _now()
                rows[i] = merged
                return copy.deepcopy(merged)
        return self.insert(table, item)

    def list(
        self,
        table: str,
        *,
        eq: dict[str, Any] | None = None,
        order: str | None = None,
        desc: bool = True,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if table == "creator_corpus_current":
            rows = [
                lean_row(p)
                for p in self.tables.get("creator_profiles", [])
                if p.get("stage") in {"classified", "scored"}
            ]
        else:
            rows = [copy.deepcopy(r) for r in self.tables.get(table, [])]
        for key, value in (eq or {}).items():
            if value is None:
                continue
            rows = [r for r in rows if r.get(key) == value]
        if order:
            rows.sort(key=lambda r: (r.get(order) is None, r.get(order) or 0), reverse=desc)
        if offset:
            rows = rows[offset:]
        if limit is not None:
            rows = rows[:limit]
        return rows

    def count(self, table: str, eq: dict[str, Any] | None = None) -> int:
        return len(self.list(table, eq=eq))

    def get(self, table: str, **eq: Any) -> dict[str, Any] | None:
        matches = self.list(table, eq=eq)
        return matches[0] if matches else None

    def update(self, table: str, values: dict[str, Any], **eq: Any) -> int:
        n = 0
        patch = {**values, "updated_at": _now()}
        rows = self.tables.setdefault(table, [])
        for i, row in enumerate(rows):
            if all(row.get(k) == v for k, v in eq.items()):
                rows[i] = {**row, **patch}
                n += 1
        return n


class SupabaseCorpus:
    def list(
        self,
        table: str,
        *,
        eq: dict[str, Any] | None = None,
        order: str | None = None,
        desc: bool = True,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        q = get_client().table(table).select("*")
        for key, value in (eq or {}).items():
            if value is None:
                continue
            q = q.eq(key, value)
        if order:
            q = q.order(order, desc=desc)
        if limit is not None:
            q = q.range(offset, offset + max(limit, 1) - 1)
        elif offset:
            q = q.range(offset, offset + 999)
        return q.execute().data or []

    def count(self, table: str, eq: dict[str, Any] | None = None) -> int:
        q = get_client().table(table).select(_pk(table), count="exact")
        for key, value in (eq or {}).items():
            if value is None:
                continue
            q = q.eq(key, value)
        return int(q.limit(1).execute().count or 0)

    def get(self, table: str, **eq: Any) -> dict[str, Any] | None:
        rows = self.list(table, eq=eq, limit=1)
        return rows[0] if rows else None

    def insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        data = get_client().table(table).insert(row).execute().data or []
        return data[0] if data else row

    def upsert(self, table: str, row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
        data = (
            get_client()
            .table(table)
            .upsert(row, on_conflict=",".join(keys))
            .execute()
            .data
            or []
        )
        return data[0] if data else row

    def update(self, table: str, values: dict[str, Any], **eq: Any) -> int:
        q = get_client().table(table).update(values)
        for key, value in eq.items():
            q = q.eq(key, value)
        data = q.execute().data or []
        return len(data)


_OVERRIDE: MemoryCorpus | SupabaseCorpus | None = None


def set_corpus(store: MemoryCorpus | SupabaseCorpus | None) -> None:
    global _OVERRIDE
    _OVERRIDE = store


def get_corpus() -> MemoryCorpus | SupabaseCorpus:
    if _OVERRIDE is not None:
        return _OVERRIDE
    return SupabaseCorpus()
