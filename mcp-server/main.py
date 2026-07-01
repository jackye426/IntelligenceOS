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
from tools.get_appointment_availability import get_appointment_availability  # noqa: E402
from tools.get_clinic_briefing import get_clinic_briefing  # noqa: E402
from tools.get_content_performance import get_content_performance  # noqa: E402
from tools.get_tiktok_marketing_insights import get_tiktok_marketing_insights  # noqa: E402
from tools.get_tiktok_content_briefing import get_tiktok_content_briefing  # noqa: E402
from tools.get_patient_demand_patterns import get_patient_demand_patterns  # noqa: E402
from tools.get_practitioner_status import get_practitioner_status  # noqa: E402
from tools.get_weekly_briefing import get_weekly_briefing  # noqa: E402
from tools.search_knowledge import search_knowledge  # noqa: E402
from tools.search_practitioners import search_practitioners  # noqa: E402

mcp = FastMCP(
    "DocMap Intelligence OS",
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
def search_knowledge_tool(
    query: str,
    entity_type: str | None = None,
    match_count: int = 5,
):
    """Search DocMap knowledge with cited chunks only."""
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
def get_content_performance_tool(platform: str | None = None, limit: int = 10):
    """Return top-performing content posts."""
    return get_content_performance(platform=platform, limit=limit)


@mcp.tool()
def get_tiktok_marketing_insights_tool(limit: int = 10):
    """Return TikTok marketing insights: top posts by saves/1k views, hooks, and A/B tests."""
    return get_tiktok_marketing_insights(limit=limit)


@mcp.tool()
def get_tiktok_content_briefing_tool(topic: str | None = None, limit: int = 5):
    """Return TikTok performance, strategy playbooks, and audience comment themes in one briefing."""
    return get_tiktok_content_briefing(topic=topic, limit=limit)


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
