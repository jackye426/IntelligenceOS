import json
from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(exist_ok=True)

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def generate_report(all_analyses, cross_clinic, output_path=None, comm_deep_dive=None, comm_analysis=None, bottleneck_data=None, inbound_deep_dive=None, opportunity_data=None):
    """Build and save a self-contained HTML report."""

    active = [a for a in all_analyses if a.get("review_count", 0) > 0]

    # ── Aggregate categories across all clinics ────────────────────────────
    category_totals: dict[str, dict] = {}
    for analysis in active:
        for cat in analysis.get("categories", []):
            name = cat["name"]
            if name not in category_totals:
                category_totals[name] = {
                    "name": name,
                    "total": 0,
                    "clinic_count": 0,
                    "severity": cat.get("severity", "medium"),
                }
            category_totals[name]["total"] += cat["count"]
            category_totals[name]["clinic_count"] += 1

    sorted_cats = sorted(category_totals.values(), key=lambda x: x["total"], reverse=True)

    # ── Heatmap: top 10 categories × all active clinics ───────────────────
    top10_names = [c["name"] for c in sorted_cats[:10]]
    heatmap_rows = []
    col_max = {name: 0 for name in top10_names}

    for analysis in active:
        cat_map = {c["name"]: c["count"] for c in analysis.get("categories", [])}
        cells = {name: cat_map.get(name, 0) for name in top10_names}
        for name, val in cells.items():
            if val > col_max[name]:
                col_max[name] = val
        heatmap_rows.append({
            "clinic": analysis["clinic"],
            "total": analysis["review_count"],
            "cells": cells,
        })

    # ── Chart data (top 12 categories) ────────────────────────────────────
    chart_cats = sorted_cats[:12]
    chart_labels = json.dumps([c["name"] for c in chart_cats])
    chart_data = json.dumps([c["total"] for c in chart_cats])
    chart_colors = json.dumps([_severity_color(c["severity"]) for c in chart_cats])

    # ── Per-clinic pie chart data ──────────────────────────────────────────
    for analysis in active:
        cats = analysis.get("categories", [])[:8]
        analysis["_pie_labels"] = json.dumps([c["name"] for c in cats])
        analysis["_pie_data"] = json.dumps([c["count"] for c in cats])
        analysis["_pie_colors"] = json.dumps([_severity_color(c.get("severity", "medium")) for c in cats])

    # ── Top complaint across all clinics ──────────────────────────────────
    top_complaint = sorted_cats[0]["name"] if sorted_cats else "N/A"

    context = {
        "report_date": datetime.now().strftime("%d %B %Y"),
        "generated_at": datetime.now().strftime("%H:%M"),
        "clinics_count": len(active),
        "total_reviews": sum(a["review_count"] for a in active),
        "top_complaint": top_complaint,
        "overall_summary": cross_clinic.get("overall_summary", ""),
        "top_themes": cross_clinic.get("top_themes", []),
        "sorted_cats": sorted_cats[:10],
        "chart_labels": chart_labels,
        "chart_data": chart_data,
        "chart_colors": chart_colors,
        "heatmap_cols": top10_names,
        "heatmap_rows": heatmap_rows,
        "col_max": col_max,
        "clinics": active,
        "all_clinics": all_analyses,
        "comm_deep_dive": comm_deep_dive,
        "comm_analysis": comm_analysis,
        "bottleneck_data": bottleneck_data,
        "inbound_deep_dive": inbound_deep_dive,
        "opportunity_data": opportunity_data,
    }

    env = Environment(
        loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report.html")
    html = template.render(**context)

    if not output_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = REPORTS_DIR / f"report_{ts}.html"

    Path(output_path).write_text(html, encoding="utf-8")
    print(f"[report] Saved -> {output_path}")
    return str(output_path)


def _severity_color(severity):
    return {"high": "#ef4444", "medium": "#f97316", "low": "#eab308"}.get(severity, "#6b7280")
