"""Allowlisted writes for creator_* tables. Never content_posts / embeddings."""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any

ALLOWED_TABLES = frozenset(
    {
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
    }
)

FORBIDDEN_TABLES = frozenset(
    {
        "content_posts",
        "document_embeddings",
        "clinic_accounts",
        "doctor_outreach",
        "gtm_clinic_intelligence",
        "gtm_clinic_people",
        "gtm_outreach_contacts",
    }
)

PRIMARY_KEYS = {
    "creator_videos": "video_id",
    "creator_specialty_stats": "specialty_key",
}

UNIQUE_KEYS: dict[str, tuple[str, ...]] = {
    "creator_seeds": ("source_type", "value"),
    "creator_profiles": ("tiktok_user_id",),
    "creator_videos": ("video_id",),
    "creator_specialty_stats": ("specialty_key",),
    "creator_discovery_hits": ("seed_id", "tiktok_user_id"),
    "creator_insight_cards": ("creator_profile_id", "classifier_version", "input_hash"),
    "creator_deep_job_items": ("kind", "item_key"),
    "creator_links": ("creator_profile_id", "target_table", "target_id"),
    "creator_peer_briefs": ("account_handle",),
}


class StoreError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _pk(table: str) -> str:
    return PRIMARY_KEYS.get(table, "id")


def _require_allowed(table: str) -> None:
    if table in FORBIDDEN_TABLES or table not in ALLOWED_TABLES:
        raise StoreError(
            f"creators store refuses table {table!r}; allowlist is creator_* only"
        )


class MemoryStore:
    """In-process stand-in used by tests and --dry-run without Supabase."""

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {t: [] for t in ALLOWED_TABLES}

    def _rows(self, table: str) -> list[dict[str, Any]]:
        _require_allowed(table)
        return self.tables.setdefault(table, [])

    def insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        _require_allowed(table)
        item = copy.deepcopy(row)
        pk = _pk(table)
        item.setdefault(pk, str(uuid.uuid4()) if pk == "id" else item.get(pk))
        item.setdefault("created_at", _now())
        item.setdefault("updated_at", _now())
        keys = UNIQUE_KEYS.get(table)
        if keys:
            for existing in self._rows(table):
                if all(existing.get(k) == item.get(k) for k in keys):
                    raise StoreError(f"duplicate {table} {keys}")
        self._rows(table).append(item)
        return copy.deepcopy(item)

    def upsert(self, table: str, row: dict[str, Any], keys: tuple[str, ...] | None = None) -> dict[str, Any]:
        _require_allowed(table)
        keys = keys or UNIQUE_KEYS.get(table) or (_pk(table),)
        item = copy.deepcopy(row)
        item.setdefault("updated_at", _now())
        rows = self._rows(table)
        for i, existing in enumerate(rows):
            if all(existing.get(k) == item.get(k) for k in keys):
                merged = {**existing, **item}
                merged["updated_at"] = _now()
                rows[i] = merged
                return copy.deepcopy(merged)
        item.setdefault("created_at", _now())
        pk = _pk(table)
        item.setdefault(pk, str(uuid.uuid4()) if pk == "id" else item.get(pk))
        rows.append(item)
        return copy.deepcopy(item)

    def get(self, table: str, **eq: Any) -> dict[str, Any] | None:
        matches = self.list(table, **eq)
        return matches[0] if matches else None

    def list(self, table: str, **eq: Any) -> list[dict[str, Any]]:
        _require_allowed(table)
        out = []
        for row in self._rows(table):
            if all(row.get(k) == v for k, v in eq.items()):
                out.append(copy.deepcopy(row))
        return out

    def update(self, table: str, values: dict[str, Any], **eq: Any) -> int:
        _require_allowed(table)
        n = 0
        patch = {**values, "updated_at": _now()}
        for i, row in enumerate(self._rows(table)):
            if all(row.get(k) == v for k, v in eq.items()):
                self.tables[table][i] = {**row, **patch}
                n += 1
        return n

    def delete(self, table: str, **eq: Any) -> int:
        _require_allowed(table)
        before = self._rows(table)
        keep = [r for r in before if not all(r.get(k) == v for k, v in eq.items())]
        n = len(before) - len(keep)
        self.tables[table] = keep
        return n

    def count(self, table: str, **eq: Any) -> int:
        return len(self.list(table, **eq))


class SupabaseStore:
    def __init__(self, client: Any) -> None:
        self.client = client

    def insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        _require_allowed(table)
        data = self.client.table(table).insert(row).execute().data or []
        return data[0] if data else row

    def upsert(self, table: str, row: dict[str, Any], keys: tuple[str, ...] | None = None) -> dict[str, Any]:
        _require_allowed(table)
        keys = keys or UNIQUE_KEYS.get(table) or (_pk(table),)
        data = (
            self.client.table(table)
            .upsert(row, on_conflict=",".join(keys))
            .execute()
            .data
            or []
        )
        return data[0] if data else row

    def get(self, table: str, **eq: Any) -> dict[str, Any] | None:
        q = self.client.table(table).select("*")
        for k, v in eq.items():
            q = q.eq(k, v)
        rows = q.limit(1).execute().data or []
        return rows[0] if rows else None

    def list(self, table: str, **eq: Any) -> list[dict[str, Any]]:
        _require_allowed(table)
        q = self.client.table(table).select("*")
        for k, v in eq.items():
            q = q.eq(k, v)
        return q.execute().data or []

    def update(self, table: str, values: dict[str, Any], **eq: Any) -> int:
        _require_allowed(table)
        q = self.client.table(table).update(values)
        for k, v in eq.items():
            q = q.eq(k, v)
        data = q.execute().data or []
        return len(data)

    def delete(self, table: str, **eq: Any) -> int:
        _require_allowed(table)
        q = self.client.table(table).delete()
        for k, v in eq.items():
            q = q.eq(k, v)
        data = q.execute().data or []
        return len(data)

    def count(self, table: str, **eq: Any) -> int:
        _require_allowed(table)
        q = self.client.table(table).select(_pk(table), count="exact")
        for k, v in eq.items():
            q = q.eq(k, v)
        return int(q.limit(1).execute().count or 0)


_OVERRIDE: MemoryStore | SupabaseStore | None = None


def set_store(store: MemoryStore | SupabaseStore | None) -> None:
    global _OVERRIDE
    _OVERRIDE = store


def get_store() -> MemoryStore | SupabaseStore:
    if _OVERRIDE is not None:
        return _OVERRIDE
    import os

    if os.getenv("CREATORS_STORE", "").lower() == "memory":
        mem = MemoryStore()
        set_store(mem)
        return mem
    from marketing_pipeline.shared.supabase_client import get_client

    return SupabaseStore(get_client())
