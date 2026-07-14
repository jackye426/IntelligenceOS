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
from common.transport_security import build_transport_security  # noqa: E402
from tools.get_appointment_availability import get_appointment_availability  # noqa: E402
from tools.get_ab_learnings import get_ab_learnings  # noqa: E402
from tools.get_clinic_briefing import get_clinic_briefing  # noqa: E402
from tools.get_content_performance import get_content_performance  # noqa: E402
from tools.get_tiktok_cohort import get_tiktok_cohort  # noqa: E402
from tools.get_tiktok_marketing_insights import get_tiktok_marketing_insights  # noqa: E402
from tools.get_tiktok_content_briefing import get_tiktok_content_briefing  # noqa: E402
from tools.get_tiktok_video import get_tiktok_video  # noqa: E402
from tools.get_tiktok_metric_layers import (  # noqa: E402
    get_tiktok_account_daily,
    get_tiktok_metric_velocity,
    get_tiktok_studio_insight,
)
from tools.find_ab_tests import find_ab_tests  # noqa: E402
from tools.record_ab_learning import record_ab_learning  # noqa: E402
from tools.get_tiktok_strategy_brief import get_tiktok_strategy_brief  # noqa: E402
from tools.get_instagram_post import get_instagram_post  # noqa: E402
from tools.get_instagram_cohort import get_instagram_cohort  # noqa: E402
from tools.get_instagram_marketing_insights import get_instagram_marketing_insights  # noqa: E402
from tools.get_instagram_strategy_brief import get_instagram_strategy_brief  # noqa: E402
from tools.tiktok_insights import (  # noqa: E402
    approve_tiktok_insight,
    draft_tiktok_insight,
    list_tiktok_insight_drafts,
    propose_constitution_patch,
)
from tools.constitution_amendments import (  # noqa: E402
    approve_constitution_amendment,
    list_constitution_amendments,
    reject_constitution_amendment,
    suggest_constitution_amendment,
)
from tools.tiktok_decisions import (  # noqa: E402
    cancel_tiktok_decision,
    get_tiktok_decision,
    list_open_decisions,
    log_tiktok_decision,
    record_decision_outcome,
)
from tools.video_components import (  # noqa: E402
    analyze_components,
    get_video_components,
    list_videos_by_component,
)
from tools.suggest_hook_repackage import suggest_hook_repackage  # noqa: E402
from tools.suggest_next_tiktok_angles import suggest_next_tiktok_angles  # noqa: E402
from tools.draft_outreach_email import draft_outreach_email  # noqa: E402
from tools.get_patient_demand_patterns import get_patient_demand_patterns  # noqa: E402
from tools.get_practitioner_status import get_practitioner_status  # noqa: E402
from tools.get_weekly_briefing import get_weekly_briefing  # noqa: E402
from tools.search_knowledge import search_knowledge  # noqa: E402
from tools.search_practitioners import search_practitioners  # noqa: E402
from tools.create_carousel import (  # noqa: E402
    create_carousel,
    fill_carousel_template,
    list_carousel_templates,
)

mcp = FastMCP(
    "DocMap Intelligence OS",
    instructions=MCP_SERVER_INSTRUCTIONS,
    stateless_http=True,
    json_response=True,
    transport_security=build_transport_security(),
)


@mcp.tool()
def search_knowledge_tool(
    query: str,
    entity_type: str | None = None,
    match_count: int = 5,
):
    """Semantic search over DocMap embeddings.

    TikTok entity_type: tiktok_transcript | content_post | tiktok_comment_batch | marketing_comment_digest | marketing_playbook.
    Instagram entity_type: content_post for post/caption/component chunks; marketing_playbook for instagram-strategy-brief.
    Prefer platform-specific tools for rankings/cohorts; use search_knowledge for semantic retrieval.
    """
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
    """Top content posts across platforms.

    Use platform=tiktok or platform=instagram to scope results.
    sort_by: views | likes | engagement | saves_per_1k | posted_at.
    For Instagram strategy work prefer get_instagram_cohort/get_instagram_marketing_insights,
    because they understand format and intent metrics.
    """
    return get_content_performance(platform=platform, limit=limit, sort_by=sort_by)  # type: ignore[arg-type]


@mcp.tool()
def get_tiktok_video_tool(video_id: str):
    """Full TikTok video: caption, transcript, hooks, comment_analysis, A/B partners, and batch-extracted `components` when synced.

    Prefer over search_knowledge for one video. Cite publish date ONLY from returned `posted_at` (UTC).
    Never decode/infer a date from video_id — TikTok snowflake time can predate public publish by days.
    If `posted_at` is null, say date unknown.
    If `components_available` is false, say components are not extracted yet (do not invent hook.type / funnel).
    For cross-video hook-type / funnel aggregates use list_videos_by_component or analyze_components.
    """
    return get_tiktok_video(video_id)


@mcp.tool()
def get_tiktok_metric_velocity_tool(video_id: str, hours: int = 48):
    """Display API snapshot velocity (views/hour) for a video over the last N hours. Requires content_metric_snapshots."""
    return get_tiktok_metric_velocity(video_id, hours=hours)


@mcp.tool()
def get_tiktok_studio_insight_tool(video_id: str):
    """Latest Studio insight metrics: avg watch time, finish rate, traffic sources, retention. Not in Display API."""
    return get_tiktok_studio_insight(video_id)


@mcp.tool()
def get_tiktok_account_daily_tool(since: str | None = None, limit: int = 90):
    """Account-day rollups from Business Center Overview.csv (includes daily profile views)."""
    return get_tiktok_account_daily(since=since, limit=limit)


@mcp.tool()
def get_tiktok_cohort_tool(
    since: str | None = None,
    until: str | None = None,
    sort_by: str = "views",
    limit: int = 50,
    tier: str = "all",
):
    """Date-filtered TikTok posts with outperform/underperform tiers. sort_by: views | engagement | saves_per_1k | likes.

    Each post's publish date is `posted_at` (UTC). Cite that field only — never infer dates from video IDs.
    """
    return get_tiktok_cohort(
        since=since,
        until=until,
        sort_by=sort_by,  # type: ignore[arg-type]
        limit=limit,
        tier=tier,  # type: ignore[arg-type]
    )


@mcp.tool()
def get_tiktok_marketing_insights_tool(
    limit: int = 15,
    sort_by: str | None = None,
    since: str | None = None,
):
    """Multi-metric TikTok rankings (views, engagement, saves/1k), cohort medians, and variant groups. Optional since=YYYY-MM-DD."""
    return get_tiktok_marketing_insights(limit=limit, sort_by=sort_by, since=since)  # type: ignore[arg-type]


@mcp.tool()
def get_tiktok_strategy_brief_tool():
    """Load the TikTok strategy brief BEFORE creative suggestions.

    Includes: constitution, approved insights (§3), open/closed decisions (§7),
    reference set, changelog, anti-patterns. Always call this (and prefer
    list_open_decisions due_only=true) before suggest_hook_repackage or
    suggest_next_tiktok_angles. Cite decision_id when building on prior decisions.
    """
    return get_tiktok_strategy_brief()


@mcp.tool()
def get_instagram_strategy_brief_tool():
    """Load the Instagram strategy brief BEFORE creative suggestions.

    Use first for: "what should we post", "what worked on Instagram", weekly review,
    content planning, or repackage ideas.

    Returns format rules, reference posts, metric freshness, and approved learnings.
    Format-first: compare Reels, carousels, and static posts separately.
    Prefer owned metrics (profile visits/follows/link taps) when present; otherwise use engagement quality.
    If found=false, tell the human Instagram has not been synced yet.
    """
    return get_instagram_strategy_brief()


@mcp.tool()
def get_instagram_post_tool(post_id: str):
    """Inspect one Instagram post by platform_post_id.

    Use after get_instagram_cohort/get_instagram_marketing_insights when explaining why a specific post worked or failed.
    Returns caption, format, metrics, deterministic components, carousel child media, source layers, and content-tracker enrichment.
    Cite post_url and posted_at from the result. Do not infer missing owned metrics as zero.
    """
    return get_instagram_post(post_id)


@mcp.tool()
def get_instagram_cohort_tool(
    since: str | None = None,
    until: str | None = None,
    sort_by: str = "intent",
    limit: int = 50,
    format: str | None = None,
    tier: str = "all",
):
    """Date-filtered Instagram posts with format filter and staleness warning.

    Use for weekly reviews, recent performance questions, and format-specific comparisons.
    sort_by:
    - intent (default): follows/profile_visits/link_taps/saves/shares/comments when present
    - engagement: likes+comments+saves+shares
    - engagement_per_1k, saves_per_1k, shares_per_1k, comments_per_1k
    - views, likes, posted_at
    format: reel | carousel | static | unknown.
    Always check staleness_warning before saying there were no recent posts.
    """
    return get_instagram_cohort(
        since=since,
        until=until,
        sort_by=sort_by,  # type: ignore[arg-type]
        limit=limit,
        format=format,
        tier=tier,  # type: ignore[arg-type]
    )


@mcp.tool()
def get_instagram_marketing_insights_tool(
    limit: int = 15,
    sort_by: str = "intent",
    since: str | None = None,
):
    """Instagram multi-metric rankings and per-format top posts.

    Use for "what worked?", "rank Instagram posts", or "compare Reels vs carousels vs static".
    Returns overall rankings plus top_by_format. Default sort_by=intent; use engagement_per_1k
    when owned metrics are sparse. Follow up with get_instagram_post for any individual post explanation.
    """
    return get_instagram_marketing_insights(
        limit=limit,
        sort_by=sort_by,  # type: ignore[arg-type]
        since=since,
    )


@mcp.tool()
def log_tiktok_decision_tool(
    decision: str,
    rationale: str | None = None,
    related_video_ids: list[str] | None = None,
    related_insight_ids: list[str] | None = None,
    group_id: str | None = None,
    action_type: str = "other",
    success_criteria: str | None = None,
    review_after: str | None = None,
    expected_signals: list[dict] | None = None,
    platform: str = "tiktok",
    status: str = "committed",
    created_by: str | None = None,
    source_session: str | None = None,
):
    """Log a FORWARD TikTok content commitment after the human agrees what to do next.

    NOT an insight (past learning) and NOT an A/B learning (pair winner takeaway).
    Use when the human commits to an action: film, repost, kill an angle, hold, or test a variant.

    Required quality: one imperative sentence in `decision` PLUS measurable `success_criteria`.
    Good: "Repost surgical-photos with imperative CTA ('always ask for photos')."
         success_criteria="saves/1k in top quartile of last 30 days within 7 days"
    Bad: "Maybe try better hooks sometime."

    action_type: repost_hook | new_film | kill_angle | hold | test_variant | other
    status: proposed | committed (default committed)
    review_after: YYYY-MM-DD when Claude should chase outcome (default +7 days)
    Link related_video_ids / related_insight_ids / group_id — do not paste long essays into rationale.
    Only call after the human clearly commits (e.g. "log that", "we'll do that").
    """
    return log_tiktok_decision(
        decision,
        rationale=rationale,
        related_video_ids=related_video_ids,
        related_insight_ids=related_insight_ids,
        group_id=group_id,
        action_type=action_type,  # type: ignore[arg-type]
        success_criteria=success_criteria,
        review_after=review_after,
        expected_signals=expected_signals,
        platform=platform,
        status=status,  # type: ignore[arg-type]
        created_by=created_by,
        source_session=source_session,
    )


@mcp.tool()
def list_open_decisions_tool(
    due_only: bool = False,
    platform: str | None = "tiktok",
    limit: int = 50,
):
    """List open TikTok decisions (status proposed|committed|done) for session start / weekly review.

    Call with due_only=true at the start of reviews — prefer closing due decisions
    (pull live metrics, propose verdict, wait for human) BEFORE inventing new experiments.
    Open = not yet outcome_recorded or cancelled.
    """
    return list_open_decisions(due_only=due_only, platform=platform, limit=limit)


@mcp.tool()
def get_tiktok_decision_tool(decision_id: str):
    """Fetch one decision by decision_id (full record: rationale, criteria, outcome, links).

    Use when citing or reviewing a specific prior commitment. Returns whether it is due.
    """
    return get_tiktok_decision(decision_id)


@mcp.tool()
def record_decision_outcome_tool(
    decision_id: str,
    verdict: str,
    metrics_summary: str | None = None,
    implication: str | None = None,
    confirmed: bool = False,
    reviewed_by: str | None = None,
):
    """Close a decision with a HUMAN-CONFIRMED verdict after tool-backed metrics.

    NEVER invent outcomes. Workflow: pull live metrics → propose verdict in chat →
    only call this after the human agrees, with confirmed=true.

    verdict: confirmed | mixed | failed | inconclusive
    implication: keep | avoid | promote_candidate | needs_another_test
    Optional next step: draft_tiktok_insight linked via related_insight_ids.
    Does NOT change constitution (use propose_constitution_patch only if human wants Gate 2).
    """
    return record_decision_outcome(
        decision_id,
        verdict=verdict,  # type: ignore[arg-type]
        metrics_summary=metrics_summary,
        implication=implication,  # type: ignore[arg-type]
        confirmed=confirmed,
        reviewed_by=reviewed_by,
    )


@mcp.tool()
def cancel_tiktok_decision_tool(
    decision_id: str,
    reason: str | None = None,
    cancelled_by: str | None = None,
):
    """Cancel an open decision that will not be executed (abandoned plan).

    Use when the human drops the commitment. Cannot cancel after outcome_recorded.
    Prefer a short reason for future Claude sessions.
    """
    return cancel_tiktok_decision(decision_id, reason=reason, cancelled_by=cancelled_by)


@mcp.tool()
def draft_tiktok_insight_tool(
    group_id: str,
    video_ids: list[str],
    what_we_tried: str,
    expectation: str | None = None,
    outcome: str | None = None,
    learning: str | None = None,
    cluster_basis: str = "manual",
    confidence: str = "medium",
    playbook_themes: list[str] | None = None,
):
    """Draft a PAST performance insight (what we observed) for user approval — Gate 1.

    Insight = retrospective learning. Do NOT use this for future commitments;
    use log_tiktok_decision when the human agrees what to film/repost next.
    Does not change constitution. User must approve via approve_tiktok_insight.
    """
    return draft_tiktok_insight(
        group_id=group_id,
        video_ids=video_ids,
        what_we_tried=what_we_tried,
        expectation=expectation,
        outcome=outcome,
        learning=learning,
        cluster_basis=cluster_basis,
        confidence=confidence,
        playbook_themes=playbook_themes,
    )


@mcp.tool()
def approve_tiktok_insight_tool(
    insight_id: str,
    approved_by: str | None = None,
    learning: str | None = None,
):
    """Approve a drafted insight — saves to approved learnings (§3) and changelog.

    Constitution unchanged. If the team also commits to a next action, separately
    call log_tiktok_decision (link related_insight_ids to this insight_id).
    """
    return approve_tiktok_insight(insight_id, approved_by=approved_by, learning=learning)


@mcp.tool()
def list_tiktok_insight_drafts_tool(limit: int = 20):
    """List insight drafts awaiting user approval (Gate 1 queue). Not the decision log."""
    return list_tiktok_insight_drafts(limit=limit)


@mcp.tool()
def propose_constitution_patch_tool(
    insight_id: str,
    proposed_bullet: str,
    target_section: str = "viral-format.md",
    rationale: str = "",
):
    """Gate 2 (legacy alias): queue a constitution amendment for human approval.

    Prefer suggest_constitution_amendment. Never auto-applies — use
    approve_constitution_amendment(..., confirmed=true) after human yes.
    """
    return propose_constitution_patch(
        insight_id=insight_id,
        proposed_bullet=proposed_bullet,
        target_section=target_section,
        rationale=rationale,
    )


@mcp.tool()
def suggest_constitution_amendment_tool(
    proposed_bullet: str,
    target_section: str = "viral-format.md",
    rationale: str = "",
    insight_id: str | None = None,
    source_group_id: str | None = None,
):
    """Propose a durable playbook rule (Gate 2 queue). Model suggests; human must approve to write.

    Use when an approved insight (or confirmed decision outcome) generalizes beyond one clip.
    Target files: viral-format.md (hooks/packaging) or content-instruction.md (audience/themes).
    """
    return suggest_constitution_amendment(
        proposed_bullet=proposed_bullet,
        target_section=target_section,
        rationale=rationale,
        insight_id=insight_id,
        source_group_id=source_group_id,
    )


@mcp.tool()
def list_constitution_amendments_tool(status: str | None = None, limit: int = 20):
    """List pending/approved/rejected constitution amendments (Gate 2 queue)."""
    return list_constitution_amendments(status=status, limit=limit)  # type: ignore[arg-type]


@mcp.tool()
def approve_constitution_amendment_tool(
    amendment_id: str,
    confirmed: bool = False,
    approved_by: str | None = None,
):
    """Apply a pending amendment after explicit human confirmation.

    Requires confirmed=true. Updates playbook in Supabase, re-embeds for search_knowledge,
    marks linked insight promoted, rebuilds brief — fully automatic, no manual scripts.
    """
    return approve_constitution_amendment(
        amendment_id=amendment_id,
        confirmed=confirmed,
        approved_by=approved_by,
    )


@mcp.tool()
def reject_constitution_amendment_tool(amendment_id: str, reason: str = ""):
    """Reject a pending constitution amendment with optional reason."""
    return reject_constitution_amendment(amendment_id=amendment_id, reason=reason)


@mcp.tool()
def find_variant_groups_tool(
    min_views: int = 0,
    hook_source: str | None = None,
    since: str | None = None,
    limit: int = 50,
    winner_by: str = "views",
    group_by_pair_id: bool = False,
):
    """TikTok variant groups (2–N videos, same audio/topic, different hooks). Alias for find_ab_tests.

    Pair-scoped discovery only. After a winner is clear: record_ab_learning for the
    takeaway; log_tiktok_decision if the human commits to a follow-up repost/film.
    """
    return find_ab_tests(
        min_views=min_views,
        hook_source=hook_source,  # type: ignore[arg-type]
        since=since,
        limit=limit,
        winner_by=winner_by,  # type: ignore[arg-type]
        group_by_pair_id=group_by_pair_id,
    )


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
    """TikTok hook A/B pairs (same content, different hook).

    winner_by: views | saves_per_1k | engagement. Set group_by_pair_id=true for multi-arm clusters.
    This finds pairs — it does not log decisions. After analysis: record_ab_learning for the
    pair takeaway; use log_tiktok_decision only if the human commits to a next action.
    """
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
    """Suggest next TikTok angles from comment themes on high-performing posts.

    Loads strategy brief + open decisions. Respect due decisions; cite decision_id when relevant.
    Suggestions are drafts — if the human commits to an angle, call log_tiktok_decision
    with success_criteria and review_after (do not only draft an insight).
    """
    return suggest_next_tiktok_angles(limit=limit, min_post_saves_per_1k=min_post_saves_per_1k)


@mcp.tool()
def suggest_hook_repackage_tool(
    video_id: str,
    reference_video_id: str | None = None,
    reference_sort_by: str = "views",
):
    """Propose hook swaps for an underperformer using top performers as reference (LLM).

    Loads strategy brief + open decisions. Human must approve before filming.
    After approval/commit: log_tiktok_decision with the chosen hook + success_criteria;
    optionally record_ab_learning when comparing against a known pair.
    """
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
    """Persist an approved A/B hook LEARNING on all videos in the pair (past takeaway).

    Pair-scoped only: who won and why. Not a future commitment — if the team will
    repost/film next, also call log_tiktok_decision. Prefer approve_tiktok_insight
    for broader (non-pair) learnings.
    """
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
    """List approved A/B hook learnings from record_ab_learning (pair history).

    For open future commitments use list_open_decisions; for approved narrative
    learnings use the strategy brief §3 insights.
    """
    return get_ab_learnings(pair_id=pair_id, since=since, limit=limit)


@mcp.tool()
def get_video_components_tool(video_id: str):
    """Read batch-extracted video components (hook type/attrs, funnel TOFU|MOFU|BOFU, CTA, topic, speaker).

    Does NOT extract live — components come from marketing_pipeline tiktok extract-components + sync.
    Joins posted_at, public metrics, and studio/velocity when available.
    Hooks-first analysis: use hook.type vocabulary, not free-form opinions.
    Cite publish date only from posted_at.
    """
    return get_video_components(video_id)


@mcp.tool()
def list_videos_by_component_tool(
    field: str = "hook.type",
    value_contains: str | None = None,
    exact_value: str | None = None,
    funnel_stage: str | None = None,
    cta_present: str | None = None,
    since: str | None = None,
    limit: int = 50,
):
    """List videos filtered by component fields (e.g. field=hook.type exact_value=direct_question).

    Optional funnel_stage=TOFU|MOFU|BOFU|unclear, cta_present=true|false|unclear.
    """
    return list_videos_by_component(
        field=field,
        value_contains=value_contains,
        exact_value=exact_value,
        funnel_stage=funnel_stage,
        cta_present=cta_present,
        since=since,
        limit=limit,
    )


@mcp.tool()
def analyze_components_tool(
    group_by: str = "hook.type",
    metric: str | None = None,
    since: str | None = None,
    funnel_stage: str | None = None,
    min_n: int = 1,
):
    """Aggregate component labels vs metrics (hooks-first: group_by=hook.type).

    metric: views | saves_per_1k | shares | engagement | comments.
    If funnel_stage set and metric omitted, defaults: TOFU→views, MOFU/BOFU→saves_per_1k.
    Never rank BOFU by views alone as commercial success. CTA conversion events not available yet.
    Retention (3s/AWT/finish) not in this aggregate — weaker without Studio joins on get_video_components.
    """
    return analyze_components(
        group_by=group_by,  # type: ignore[arg-type]
        metric=metric,  # type: ignore[arg-type]
        since=since,
        funnel_stage=funnel_stage,
        min_n=min_n,
    )


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


@mcp.tool()
def list_carousel_templates_tool():
    """List the 5 DocMap carousel PPTX templates (id, name, description, best_for).

    Call before create_carousel when the human wants to pick a visual style.
    Templates: classic_blue, photo_center_hook, photo_body_left, photo_body_right, minimal_white.
    """
    return list_carousel_templates()


@mcp.tool()
def create_carousel_tool(
    topic: str,
    angle: str | None = None,
    context: str | None = None,
    template_id: str | None = None,
    slide_count: int = 6,
    audience_notes: str | None = None,
):
    """Generate carousel copy, pick a template (unless template_id set), and export a filled PPTX.

    Text is auto-wrapped and font-sized per slide zone to avoid overflow.
    Returns carousel JSON, layout_metrics, pptx_filename, and pptx_base64 for download.
    Import the PPTX into Adobe Express for final graphics/fonts.

    Workflow: optionally pull patient voice / IG performance via other tools first, pass as context.
    """
    return create_carousel(
        topic=topic,
        angle=angle,
        context=context,
        template_id=template_id,
        slide_count=slide_count,
        audience_notes=audience_notes,
    )


@mcp.tool()
def fill_carousel_template_tool(
    template_id: str,
    topic: str,
    hook: str,
    slides: list[dict[str, str]],
    cta: str,
    caption: str,
    hook_subtitle: str | None = None,
):
    """Fill a carousel template with copy you already wrote (no extra LLM call).

    Each slide dict needs main_text and subtext. Text is auto-sized to fit zones.
    Returns pptx_base64 — import into Adobe Express for design polish.
    """
    return fill_carousel_template(
        template_id=template_id,
        topic=topic,
        hook=hook,
        slides=slides,
        cta=cta,
        caption=caption,
        hook_subtitle=hook_subtitle,
    )


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
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
