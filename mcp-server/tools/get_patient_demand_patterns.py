"""Aggregated patient demand patterns from conversation metadata."""

from __future__ import annotations

from collections import Counter
from typing import Any

from common.audit import log_tool_call
from common.supabase_client import get_client


def get_patient_demand_patterns(limit: int = 20) -> dict[str, Any]:
    summary = f"limit={limit}"
    try:
        rows = (
            get_client()
            .table("patient_conversations")
            .select("condition_tags, need_tags, message_count, conversation_date")
            .order("conversation_date", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )

        conditions: Counter[str] = Counter()
        needs: Counter[str] = Counter()
        for row in rows:
            for tag in row.get("condition_tags") or []:
                conditions[tag] += 1
            for tag in row.get("need_tags") or []:
                needs[tag] += 1

        result = {
            "conversation_count": len(rows),
            "top_conditions": conditions.most_common(10),
            "top_needs": needs.most_common(10),
            "recent_conversations": [
                {
                    "conversation_date": row.get("conversation_date"),
                    "message_count": row.get("message_count"),
                    "condition_tags": row.get("condition_tags") or [],
                    "need_tags": row.get("need_tags") or [],
                }
                for row in rows[:10]
            ],
        }
        log_tool_call(
            tool_name="get_patient_demand_patterns",
            request_summary=summary,
            success=True,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="get_patient_demand_patterns",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise
