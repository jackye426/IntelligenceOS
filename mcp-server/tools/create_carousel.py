"""MCP carousel creation tools."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from common.audit import log_tool_call
from carousel.pptx_builder import build_carousel_pptx, load_templates
from carousel.writer import draft_to_content, generate_carousel_copy

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output" / "carousels"


def list_carousel_templates() -> list[dict[str, Any]]:
    summary = "list templates"
    try:
        result = [
            {
                "id": t["id"],
                "name": t["name"],
                "description": t.get("description", ""),
                "best_for": t.get("best_for", []),
            }
            for t in load_templates()
        ]
        log_tool_call(tool_name="list_carousel_templates", request_summary=summary, success=True)
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="list_carousel_templates",
            request_summary=summary,
            success=False,
            error=str(exc),
        )
        raise


def create_carousel(
    *,
    topic: str,
    angle: str | None = None,
    context: str | None = None,
    template_id: str | None = None,
    slide_count: int = 6,
    audience_notes: str | None = None,
    include_pptx_base64: bool = True,
) -> dict[str, Any]:
    summary = f"topic={topic[:80]}, template={template_id}, slides={slide_count}"
    try:
        draft = generate_carousel_copy(
            topic=topic,
            angle=angle,
            context=context,
            template_id=template_id,
            slide_count=slide_count,
            audience_notes=audience_notes,
        )
        content = draft_to_content(draft)
        out_path, metrics = build_carousel_pptx(content, out_dir=OUTPUT_DIR)

        result: dict[str, Any] = {
            "carousel": {
                "topic": draft.topic,
                "template_id": draft.template_id,
                "template_reason": draft.template_reason,
                "hook": draft.hook,
                "hook_subtitle": draft.hook_subtitle,
                "slides": [s.model_dump() for s in draft.slides],
                "cta": draft.cta,
                "caption": draft.caption,
            },
            "layout_metrics": metrics,
            "pptx_filename": out_path.name,
            "pptx_path": str(out_path),
            "import_hint": (
                "Open the PPTX in Adobe Express (File → Upload → PowerPoint) or PowerPoint. "
                "All slides are filled with auto-sized text. Swap background images and fonts in Express."
            ),
        }

        if include_pptx_base64:
            result["pptx_base64"] = base64.b64encode(out_path.read_bytes()).decode("ascii")

        log_tool_call(
            tool_name="create_carousel",
            request_summary=summary,
            success=True,
            action_type="write",
            metadata={
                "template_id": draft.template_id,
                "slide_count": len(draft.slides),
                "overflow_warning": metrics.get("overflow_warning"),
            },
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="create_carousel",
            request_summary=summary,
            success=False,
            error=str(exc),
            action_type="write",
        )
        raise


def fill_carousel_template(
    *,
    template_id: str,
    topic: str,
    hook: str,
    slides: list[dict[str, str]],
    cta: str,
    caption: str,
    hook_subtitle: str | None = None,
    include_pptx_base64: bool = True,
) -> dict[str, Any]:
    """Fill a template with pre-written copy (no LLM). Useful when Claude writes copy itself."""
    from carousel.pptx_builder import CarouselContent, get_template

    summary = f"fill template={template_id}, topic={topic[:60]}"
    try:
        get_template(template_id)
        content = CarouselContent(
            topic=topic,
            template_id=template_id,
            hook=hook,
            hook_subtitle=hook_subtitle,
            slides=slides,
            cta=cta,
            caption=caption,
        )
        out_path, metrics = build_carousel_pptx(content, out_dir=OUTPUT_DIR)

        result: dict[str, Any] = {
            "template_id": template_id,
            "layout_metrics": metrics,
            "pptx_filename": out_path.name,
            "pptx_path": str(out_path),
            "import_hint": (
                "Open the PPTX in Adobe Express. Text is auto-sized per zone. "
                "Adjust fonts/graphics in Express for final polish."
            ),
        }
        if include_pptx_base64:
            result["pptx_base64"] = base64.b64encode(out_path.read_bytes()).decode("ascii")

        log_tool_call(
            tool_name="fill_carousel_template",
            request_summary=summary,
            success=True,
            action_type="write",
            metadata={"template_id": template_id, "overflow_warning": metrics.get("overflow_warning")},
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log_tool_call(
            tool_name="fill_carousel_template",
            request_summary=summary,
            success=False,
            error=str(exc),
            action_type="write",
        )
        raise
