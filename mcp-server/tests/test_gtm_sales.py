"""MCP GTM sales wrap: cap, cohort, no draft."""

from __future__ import annotations

import pytest

from tools import gtm_sales


def test_list_gtm_ready_for_sales_cap(monkeypatch):
    import sys
    from pathlib import Path

    gtm_src = str(Path(__file__).resolve().parents[2] / "gtm-pipeline" / "src")
    if gtm_src not in sys.path:
        sys.path.insert(0, gtm_src)

    seen = {}

    def fake_list(*, limit=200, cohort=None):
        seen["limit"] = limit
        seen["cohort"] = cohort
        return {
            "contacts": [
                {
                    "clinic_intelligence_id": "cl-1",
                    "evidence": [{"kind": "tiktok_creator_angle", "value": {"handle": "drjane"}}],
                    "status": "ready",
                }
            ],
            "returned": 1,
        }

    monkeypatch.setattr(gtm_sales, "log_tool_call", lambda **kwargs: None)
    import gtm_pipeline.contacts.outreach as outreach

    monkeypatch.setattr(outreach, "list_ready_for_sales", fake_list)
    out = gtm_sales.list_gtm_ready_for_sales(cohort="tiktok_doctor_creators", limit=500)
    assert seen["limit"] == 100
    assert seen["cohort"] == "tiktok_doctor_creators"
    assert out["contacts"][0]["evidence"][0]["kind"] == "tiktok_creator_angle"


def test_list_gtm_ready_rejects_zero_limit():
    with pytest.raises(gtm_sales.GtmSalesError):
        gtm_sales.list_gtm_ready_for_sales(limit=0)


def test_get_gtm_contact_includes_angle(monkeypatch):
    class _Result:
        def __init__(self, data):
            self.data = data

    class _Q:
        def __init__(self, rows):
            self.rows = rows

        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def execute(self):
            return _Result(self.rows)

    class _C:
        def table(self, name):
            if name == "gtm_clinic_intelligence":
                return _Q(
                    [
                        {
                            "id": "cl-1",
                            "clinic_name": "Jane",
                            "source_creator_profile_id": "p1",
                            "evidence": [],
                        }
                    ]
                )
            if name == "gtm_clinic_people":
                return _Q([{"id": "pe1", "full_name": "Dr Jane", "creator_profile_id": "p1"}])
            return _Q(
                [
                    {
                        "id": "c1",
                        "status": "ready",
                        "evidence": [{"kind": "tiktok_creator_angle", "value": {"handle": "drjane"}}],
                    }
                ]
            )

    monkeypatch.setattr(gtm_sales, "log_tool_call", lambda **kwargs: None)
    monkeypatch.setattr(gtm_sales, "get_client", lambda: _C())
    out = gtm_sales.get_gtm_contact("cl-1")
    assert out["ready"] is True
    assert out["tiktok_creator_angle"]["value"]["handle"] == "drjane"
    assert "draft" not in out["note"].lower() or "Draft only" in out["note"]
