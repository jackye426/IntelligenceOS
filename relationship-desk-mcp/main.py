"""
Relationship Desk MCP.

Local run:
  cd relationship-desk-mcp
  pip install -r requirements.txt
  python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from common import config  # noqa: E402
from common.auth import AuthMiddleware  # noqa: E402
from common.instructions import RELATIONSHIP_DESK_INSTRUCTIONS  # noqa: E402
from common.transport_security import build_transport_security  # noqa: E402
from tools import act_on_chase, capture_chase, chase_state, draft_chase, list_chases  # noqa: E402
from tools import followup_candidates, relationship_desk, review_inbox_since, sync_replies, thread_tools  # noqa: E402

mcp = FastMCP(
    "Relationship Desk",
    instructions=RELATIONSHIP_DESK_INSTRUCTIONS,
    stateless_http=True,
    json_response=True,
    transport_security=build_transport_security(),
)


@mcp.tool()
def relationship_desk_tool(instruction: str, limit: int = 10) -> dict[str, Any]:
    """Handle minimal relationship instructions: review due chases, capture a chase, draft due chases, or send safe ones."""
    return relationship_desk.run(instruction=instruction, limit=limit)


@mcp.tool()
def list_chases_tool(
    status: str | None = None,
    due_before: str | None = None,
    limit: int = 30,
    include_done: bool = False,
) -> dict[str, Any]:
    """List tracked chase items. Use due_before with an ISO timestamp to answer who still needs chasing."""
    return list_chases.run(status=status, due_before=due_before, limit=limit, include_done=include_done)


@mcp.tool()
def review_due_chases_tool(limit: int = 20) -> dict[str, Any]:
    """List chases due now. Use first for 'who do we still need to chase?'."""
    return list_chases.due_now(limit=limit)


@mcp.tool()
def capture_chase_tool(
    instruction: str,
    contact_hint: str | None = None,
    email: str | None = None,
    objective: str | None = None,
    why_it_matters: str | None = None,
    needed_response: str | None = None,
    next_chase_due_at: str | None = None,
    gmail_thread_id: str | None = None,
    send_mode: str = "requires_approval",
) -> dict[str, Any]:
    """Create a tracked chase from minimal direction and optional contact/thread details."""
    return capture_chase.run(
        instruction=instruction,
        contact_hint=contact_hint,
        email=email,
        objective=objective,
        why_it_matters=why_it_matters,
        needed_response=needed_response,
        next_chase_due_at=next_chase_due_at,
        gmail_thread_id=gmail_thread_id,
        send_mode=send_mode,
    )


@mcp.tool()
def search_threads_tool(query: str, max_results: int = 10) -> dict[str, Any]:
    """Search Gmail threads using Gmail query syntax."""
    return thread_tools.search(query=query, max_results=max_results)


@mcp.tool()
def get_thread_brief_tool(gmail_thread_id: str) -> dict[str, Any]:
    """Read and summarize a Gmail thread for relationship context."""
    return thread_tools.brief(gmail_thread_id=gmail_thread_id)


@mcp.tool()
def review_inbox_since_tool(since: str, max_results: int = 20) -> dict[str, Any]:
    """Review inbox threads after a Gmail date string such as 2026/7/1."""
    return review_inbox_since.run(since=since, max_results=max_results)


@mcp.tool()
def scan_inbox_for_followups_tool(
    since: str | None = None,
    hours_back: int = 72,
    max_results: int = 30,
    auto_convert_high_confidence: bool = False,
    min_confidence: float = 0.65,
) -> dict[str, Any]:
    """Scan recent Gmail inbox threads and create suggested follow-up candidates.

    This does not send email. By default it only creates candidates for review.
    """
    return followup_candidates.scan_inbox(
        since=since,
        hours_back=hours_back,
        max_results=max_results,
        auto_convert_high_confidence=auto_convert_high_confidence,
        min_confidence=min_confidence,
    )


@mcp.tool()
def review_followup_candidates_tool(
    status: str = "suggested",
    limit: int = 30,
    min_confidence: float | None = None,
) -> dict[str, Any]:
    """Review suggested follow-ups found by inbox scanning."""
    return followup_candidates.review(status=status, limit=limit, min_confidence=min_confidence)


@mcp.tool()
def accept_followup_candidate_tool(candidate_id: str) -> dict[str, Any]:
    """Convert a suggested follow-up candidate into a tracked chase."""
    return followup_candidates.accept(candidate_id)


@mcp.tool()
def ignore_followup_candidate_tool(candidate_id: str, reason: str | None = None) -> dict[str, Any]:
    """Ignore a follow-up candidate so it does not keep appearing as suggested."""
    return followup_candidates.ignore(candidate_id, reason=reason)


@mcp.tool()
def sync_replies_tool(limit: int = 50) -> dict[str, Any]:
    """Detect replies on tracked Gmail threads and move matching chases to replied."""
    return sync_replies.run(limit=limit)


@mcp.tool()
def draft_chase_tool(chase_id: str, tone: str = "warm") -> dict[str, Any]:
    """Draft follow-up copy for a tracked chase without touching Gmail."""
    return draft_chase.run(chase_id=chase_id, tone=tone)


@mcp.tool()
def act_on_chase_tool(
    chase_id: str,
    action: str = "draft",
    confirmed: bool = False,
    subject: str | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    """Create a Gmail draft or send when Relationship Desk mode and safety rules allow it."""
    return act_on_chase.run(
        chase_id=chase_id,
        action=action,
        confirmed=confirmed,
        subject=subject,
        body=body,
    )


@mcp.tool()
def get_relationship_brief_tool(chase_id: str) -> dict[str, Any]:
    """Get a chase, contact, and recent event history."""
    return chase_state.relationship_brief(chase_id=chase_id)


@mcp.tool()
def mark_waiting_tool(chase_id: str, next_chase_due_at: str | None = None, note: str | None = None) -> dict[str, Any]:
    """Mark a chase as waiting and set the next chase date."""
    return chase_state.mark_waiting(chase_id=chase_id, next_chase_due_at=next_chase_due_at, note=note)


@mcp.tool()
def mark_done_tool(chase_id: str, outcome: str | None = None) -> dict[str, Any]:
    """Mark a chase complete with an optional outcome note."""
    return chase_state.mark_done(chase_id=chase_id, outcome=outcome)


@mcp.tool()
def snooze_chase_tool(chase_id: str, until: str, note: str | None = None) -> dict[str, Any]:
    """Snooze a chase until an ISO timestamp."""
    return chase_state.snooze(chase_id=chase_id, until=until, note=note)


async def health(request):  # noqa: ANN001
    return JSONResponse(
        {
            "status": "ok",
            "service": "relationship-desk",
            "mode": config.DESK_MODE,
            "practitioners_table": config.PRACTITIONERS_TABLE,
        }
    )


async def root(request):  # noqa: ANN001
    return JSONResponse(
        {
            "service": "Relationship Desk",
            "description": "Gmail relationship follow-up memory, drafting, and supervised sending MCP.",
            "health": "/health",
        }
    )


app = mcp.streamable_http_app()
app.router.routes.append(Route("/", root, methods=["GET"]))
app.router.routes.append(Route("/health", health, methods=["GET"]))
app.user_middleware.append(Middleware(AuthMiddleware))
app.middleware_stack = app.build_middleware_stack()


if __name__ == "__main__":
    uvicorn.run(app, host=config.HOST, port=config.PORT)
