"""
DocMap Intelligence OS — hosted MCP server.

Local run:
  cd mcp-server
  pip install -r requirements.txt
  python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from common.auth import AuthMiddleware  # noqa: E402
from common import config  # noqa: E402
from common.mcp_instructions import MCP_SERVER_INSTRUCTIONS  # noqa: E402
from tools.get_appointment_availability import get_appointment_availability  # noqa: E402
from tools.get_ab_learnings import get_ab_learnings  # noqa: E402
from tools.get_clinic_briefing import get_clinic_briefing  # noqa: E402
from tools.get_content_performance import get_content_performance  # noqa: E402
from tools.get_tiktok_cohort import get_tiktok_cohort  # noqa: E402
from tools.get_tiktok_marketing_insights import get_tiktok_marketing_insights  # noqa: E402
from tools.get_tiktok_content_briefing import get_tiktok_content_briefing  # noqa: E402
from tools.get_tiktok_video import get_tiktok_video  # noqa: E402
from tools.find_ab_tests import find_ab_tests  # noqa: E402
from tools.record_ab_learning import record_ab_learning  # noqa: E402
from tools.suggest_hook_repackage import suggest_hook_repackage  # noqa: E402
from tools.suggest_next_tiktok_angles import suggest_next_tiktok_angles  # noqa: E402
from tools.draft_outreach_email import draft_outreach_email  # noqa: E402
from tools.get_patient_demand_patterns import get_patient_demand_patterns  # noqa: E402
from tools.get_practitioner_status import get_practitioner_status  # noqa: E402
from tools.get_weekly_briefing import get_weekly_briefing  # noqa: E402
from tools.search_knowledge import search_knowledge  # noqa: E402
from tools.search_practitioners import search_practitioners  # noqa: E402

mcp = FastMCP(
    "DocMap Intelligence OS",
    instructions=MCP_SERVER_INSTRUCTIONS,
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
def search_knowledge_tool(
    query: str,
    entity_type: str | None = None,
    match_count: int = 5,
):
    """Semantic search over DocMap embeddings. TikTok: entity_type tiktok_transcript | content_post | marketing_playbook | marketing_comment_digest."""
    return search_knowledge(query, entity_type=entity_type, match_count=match_count)


@mcp.tool()
def search_practitioners_tool(query: str, limit: int = 10):
    """Search practitioners by name, email, or specialty."""
    return search_practitioners(query, limit=limit)


@mcp.tool()
def get_practitioner_status_tool(practitioner_id: str):
    """Get outreach status for a practitioner."""
    return get_practitioner_status(practitioner_id)


@mcp.tool()
def get_clinic_briefing_tool(clinic_account_id: str):
    """Get a clinic account briefing with approved observations and contacts."""
    return get_clinic_briefing(clinic_account_id)


@mcp.tool()
def get_patient_demand_patterns_tool(limit: int = 20):
    """Summarize recent patient demand tags from conversation metadata."""
    return get_patient_demand_patterns(limit=limit)


@mcp.tool()
def get_content_performance_tool(
    platform: str | None = None,
    limit: int = 20,
    sort_by: str = "views",
):
    """Top content posts. sort_by: views | likes | engagement | saves_per_1k | posted_at. Use platform=tiktok for full TikTok catalog."""
    return get_content_performance(platform=platform, limit=limit, sort_by=sort_by)  # type: ignore[arg-type]


@mcp.tool()
def get_tiktok_video_tool(video_id: str):
    """Full TikTok video: caption, transcript, hooks (spoken/caption/onscreen), comment_analysis, A/B partners. Prefer over search_knowledge for one video."""
    return get_tiktok_video(video_id)


@mcp.tool()
def get_tiktok_cohort_tool(
    since: str | None = None,
    until: str | None = None,
    sort_by: str = "views",
    limit: int = 50,
    tier: str = "all",
):
    """Date-filtered TikTok posts with outperform/underperform tiers. sort_by: views | engagement | saves_per_1k | likes."""
    return get_tiktok_cohort(
        since=since,
        until=until,
        sort_by=sort_by,  # type: ignore[arg-type]
        limit=limit,
        tier=tier,  # type: ignore[arg-type]
    )


@mcp.tool()
def get_tiktok_marketing_insights_tool(limit: int = 15, sort_by: str | None = None):
    """Multi-metric TikTok rankings (views, engagement, saves/1k), cohort medians, and A/B tests. Raise limit for batch reviews."""
    return get_tiktok_marketing_insights(limit=limit, sort_by=sort_by)  # type: ignore[arg-type]


@mcp.tool()
def get_tiktok_content_briefing_tool(topic: str | None = None, limit: int = 5):
    """Composite briefing: TikTok performance, playbooks, audience comment themes."""
    return get_tiktok_content_briefing(topic=topic, limit=limit)


@mcp.tool()
def find_ab_tests_tool(
    min_views: int = 0,
    hook_source: str | None = None,
    since: str | None = None,
    limit: int = 50,
    winner_by: str = "views",
    group_by_pair_id: bool = False,
):
    """TikTok hook A/B pairs (same content, different hook). winner_by: views | saves_per_1k | engagement. Set group_by_pair_id=true for multi-arm clusters."""
    return find_ab_tests(
        min_views=min_views,
        hook_source=hook_source,  # type: ignore[arg-type]
        since=since,
        limit=limit,
        winner_by=winner_by,  # type: ignore[arg-type]
        group_by_pair_id=group_by_pair_id,
    )


@mcp.tool()
def suggest_next_tiktok_angles_tool(limit: int = 15, min_post_saves_per_1k: float = 0.0):
    """Suggest next TikTok angles from comment theme analysis on high-performing posts."""
    return suggest_next_tiktok_angles(limit=limit, min_post_saves_per_1k=min_post_saves_per_1k)


@mcp.tool()
def suggest_hook_repackage_tool(
    video_id: str,
    reference_video_id: str | None = None,
    reference_sort_by: str = "views",
):
    """Propose hook swaps for an underperformer using top performers as reference (LLM). Human must approve before filming."""
    return suggest_hook_repackage(
        video_id,
        reference_video_id=reference_video_id,
        reference_sort_by=reference_sort_by,  # type: ignore[arg-type]
    )


@mcp.tool()
def record_ab_learning_tool(
    pair_id: str,
    learning: str,
    winner_video_id: str,
    hook_pattern: str | None = None,
    confidence: str = "medium",
    loser_video_id: str | None = None,
    reposted_as: str | None = None,
    reviewed_by: str | None = None,
):
    """Persist approved A/B hook learning to Supabase on all videos in the pair."""
    return record_ab_learning(
        pair_id,
        learning,
        winner_video_id,
        hook_pattern=hook_pattern,
        confidence=confidence,  # type: ignore[arg-type]
        loser_video_id=loser_video_id,
        reposted_as=reposted_as,
        reviewed_by=reviewed_by,
    )


@mcp.tool()
def get_ab_learnings_tool(pair_id: str | None = None, since: str | None = None, limit: int = 50):
    """List approved A/B hook learnings recorded via record_ab_learning."""
    return get_ab_learnings(pair_id=pair_id, since=since, limit=limit)


@mcp.tool()
def draft_outreach_email_tool(
    subject: str,
    body: str,
    confirmed: bool = False,
    to_email: str | None = None,
    practitioner_id: str | None = None,
):
    """Create a Gmail draft for outreach (never sends). Requires confirmed=true after human review."""
    return draft_outreach_email(
        subject=subject,
        body=body,
        to_email=to_email,
        confirmed=confirmed,
        practitioner_id=practitioner_id,
    )


@mcp.tool()
def get_appointment_availability_tool(
    practitioner_name: str | None = None,
    limit: int = 20,
):
    """Return upcoming visible appointment slots."""
    return get_appointment_availability(practitioner_name=practitioner_name, limit=limit)


@mcp.tool()
def get_weekly_briefing_tool():
    """Return a weekly cross-source operational briefing."""
    return get_weekly_briefing()


async def health(_request):
    return JSONResponse({"status": "ok", "service": "docmap-mcp"})


app = mcp.streamable_http_app()
app.routes.insert(0, Route("/health", health))
app.user_middleware.insert(0, Middleware(AuthMiddleware))


def main() -> None:
    import uvicorn

    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
