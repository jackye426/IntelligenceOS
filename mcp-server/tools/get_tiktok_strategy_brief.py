"""Return assembled TikTok strategy brief from Supabase."""

from __future__ import annotations

from typing import Any

from common.audit import log_tool_call
from tools.tiktok_strategy_state import fetch_strategy_brief


def get_tiktok_strategy_brief() -> dict[str, Any]:
    try:
        result = fetch_strategy_brief()
        log_tool_call(tool_name="get_tiktok_strategy_brief", request_summary="", success=result.get("ok", False))
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(tool_name="get_tiktok_strategy_brief", request_summary="", success=False, error=str(exc))
        raise
