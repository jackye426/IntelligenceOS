"""Creator-corpus GTM handoff: cohort branch, evidence select, tiktok_bio."""

from __future__ import annotations

from gtm_pipeline.contacts import outreach
from gtm_pipeline.segments import refresh_cohort


class _Result:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count if count is not None else (len(data) if data is not None else 0)


class _Query:
    def __init__(self, client: "FakeClient", table: str):
        self.client = client
        self.table = table
        self._eq: dict = {}
        self._in: dict = {}
        self._action = "select"
        self._payload = None
        self._range = None
        self._limit = None

    def select(self, *_cols, count=None):
        self._action = "select"
        self._count = count
        return self

    def eq(self, key, value):
        self._eq[key] = value
        return self

    def in_(self, key, values):
        self._in[key] = set(values)
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def update(self, payload):
        self._action = "update"
        self._payload = payload
        return self

    def insert(self, payload):
        self._action = "insert"
        self._payload = payload
        return self

    def delete(self):
        self._action = "delete"
        return self

    def _filtered(self):
        rows = list(self.client.data.get(self.table, []))
        for key, value in self._eq.items():
            rows = [r for r in rows if r.get(key) == value]
        for key, values in self._in.items():
            rows = [r for r in rows if r.get(key) in values]
        return rows

    def execute(self):
        if self._action == "delete":
            keep = []
            for row in self.client.data.get(self.table, []):
                if all(row.get(k) == v for k, v in self._eq.items()):
                    continue
                keep.append(row)
            self.client.data[self.table] = keep
            return _Result([])
        if self._action == "insert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            self.client.data.setdefault(self.table, []).extend(payload)
            return _Result(payload)
        if self._action == "update":
            updated = []
            for row in self.client.data.get(self.table, []):
                if all(row.get(k) == v for k, v in self._eq.items()):
                    row.update(self._payload)
                    updated.append(row)
            return _Result(updated)
        rows = self._filtered()
        if self._range:
            start, end = self._range
            rows = rows[start : end + 1]
        if self._limit:
            rows = rows[: self._limit]
        return _Result(rows)


class FakeClient:
    def __init__(self, data: dict):
        self.data = data

    def table(self, name: str) -> _Query:
        return _Query(self, name)


def _seed():
    return {
        "gtm_outreach_cohorts": [
            {
                "id": "co-creator",
                "slug": "tiktok_doctor_creators",
                "rules": {"source": "creator_corpus", "require_people": True},
                "priority": 85,
                "active": True,
            },
            {
                "id": "co-generic",
                "slug": "solo_og",
                "rules": {"sizes": ["group"], "specialty_keys": ["obstetrics_gynaecology"]},
                "priority": 50,
                "active": True,
            },
        ],
        "gtm_clinic_intelligence": [
            {
                "id": "cl-creator",
                "clinic_name": "Jane Clinic",
                "visible_clinic_size": "solo",
                "specialties": ["colorectal"],
                "founder_score": 12,
                "source_creator_profile_id": "p1",
                "website_url": "https://jane.clinic",
                "cqc_nominated_individual": "",
                "cqc_registered_manager": "",
            },
            {
                "id": "cl-generic",
                "clinic_name": "Group OG",
                "visible_clinic_size": "group",
                "specialties": ["obstetrics_gynaecology"],
                "founder_score": 40,
                "source_creator_profile_id": None,
                "website_url": "https://og.example",
                "cqc_nominated_individual": "Dr NI",
                "cqc_registered_manager": "",
            },
        ],
        "gtm_clinic_people": [
            {
                "id": "pe1",
                "clinic_intelligence_id": "cl-creator",
                "full_name": "Dr Jane",
                "role": "specialist",
                "specialty": "colorectal",
                "email": "jane@clinic.co.uk",
                "priority": 50,
                "linkedin_url": None,
                "linkedin_status": None,
                "creator_profile_id": "p1",
            },
            {
                "id": "pe2",
                "clinic_intelligence_id": "cl-generic",
                "full_name": "Dr NI",
                "role": "nominated_individual",
                "specialty": "obstetrics_gynaecology",
                "email": "ni@og.example",
                "priority": 95,
                "linkedin_url": None,
                "linkedin_status": None,
                "creator_profile_id": None,
            },
        ],
        "gtm_outreach_cohort_members": [],
        "gtm_outreach_contacts": [
            {
                "id": "c1",
                "clinic_intelligence_id": "cl-creator",
                "full_name": "Dr Jane",
                "role": "specialist",
                "email": "jane@clinic.co.uk",
                "email_source": "tiktok_bio",
                "status": "ready",
                "founder_score": 12,
                "preferred_channel": "email",
                "evidence": [{"kind": "tiktok_profile", "handle": "drjane"}],
                "provenance": {"source": "creator_corpus"},
            }
        ],
    }


def test_refresh_cohort_creator_source_branch(monkeypatch):
    client = FakeClient(_seed())
    monkeypatch.setattr("gtm_pipeline.segments.supabase_configured", lambda: True)
    monkeypatch.setattr("gtm_pipeline.segments.get_client", lambda: client)

    creator = refresh_cohort("tiktok_doctor_creators")
    assert creator["matched"] == 1
    members = client.data["gtm_outreach_cohort_members"]
    assert members[0]["clinic_intelligence_id"] == "cl-creator"
    assert members[0]["reasons"] == [{"source": "creator_corpus"}]

    generic = refresh_cohort("solo_og")
    assert generic["matched"] == 1
    remaining = [
        m for m in client.data["gtm_outreach_cohort_members"] if m["cohort_id"] == "co-creator"
    ]
    assert remaining, "generic cohort refresh must not delete tiktok_doctor_creators members"


def test_list_ready_for_sales_includes_evidence(monkeypatch):
    client = FakeClient(_seed())
    monkeypatch.setattr("gtm_pipeline.contacts.outreach.supabase_configured", lambda: True)
    monkeypatch.setattr("gtm_pipeline.contacts.outreach.get_client", lambda: client)

    out = outreach.list_ready_for_sales(limit=10)
    assert out["returned"] == 1
    row = out["contacts"][0]
    assert row["evidence"][0]["handle"] == "drjane"
    assert row["clinic_name"] == "Jane Clinic"
    assert row["website_url"] == "https://jane.clinic"
    assert row["specialties"] == ["colorectal"]
    assert row["source_creator_profile_id"] == "p1"
    assert "evidence" in outreach.list_outreach_contacts(status="ready")["contacts"][0]


def test_list_ready_for_sales_cohort_filter(monkeypatch):
    client = FakeClient(_seed())
    client.data["gtm_outreach_cohort_members"] = [
        {"cohort_id": "co-creator", "clinic_intelligence_id": "cl-creator"}
    ]
    monkeypatch.setattr("gtm_pipeline.contacts.outreach.supabase_configured", lambda: True)
    monkeypatch.setattr("gtm_pipeline.contacts.outreach.get_client", lambda: client)
    monkeypatch.setattr("gtm_pipeline.contacts.outreach.get_cohort", lambda slug: client.data["gtm_outreach_cohorts"][0])
    monkeypatch.setattr(
        "gtm_pipeline.contacts.outreach.list_members",
        lambda slug, status=None, limit=5000: {
            "members": [{"clinic_intelligence_id": "cl-creator"}]
        },
    )
    out = outreach.list_ready_for_sales(limit=10, cohort="tiktok_doctor_creators")
    assert out["returned"] == 1
    assert out["contacts"][0]["source_creator_profile_id"] == "p1"
