"""Creator promotion uses existing GTM upserts and never creates clinic_accounts."""

from __future__ import annotations

import inspect

from gtm_pipeline.creators import promote as promote_mod
from gtm_pipeline.creators.promote import eligible, promote_creators, tiktok_creator_angle


class _Result:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count if count is not None else (len(data) if data is not None else 0)


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self._eq = {}
        self._action = "select"
        self._payload = None
        self._range = None

    def select(self, *_cols, count=None):
        self._action = "select"
        return self

    def eq(self, key, value):
        self._eq[key] = value
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def limit(self, n):
        return self

    def update(self, payload):
        self._action = "update"
        self._payload = payload
        return self

    def insert(self, payload):
        self._action = "insert"
        self._payload = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self._action = "insert"
        self._payload = payload
        return self

    def execute(self):
        rows = [r for r in self.client.data.get(self.table, []) if all(r.get(k) == v for k, v in self._eq.items())]
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
        if self._range:
            start, end = self._range
            rows = rows[start : end + 1]
        return _Result(rows)


class FakeClient:
    def __init__(self, data):
        self.data = data

    def table(self, name):
        return _Query(self, name)


def _profile(**extra):
    row = {
        "id": "p1",
        "handle": "drjane",
        "nickname": "Dr Jane Smith",
        "profile_url": "https://www.tiktok.com/@drjane",
        "geo_country": "GB",
        "lane": "customer",
        "review_status": "confirmed",
        "do_not_contact": False,
        "specialty_key": "colorectal",
        "customer_score": 72,
        "follower_count": 12000,
        "posts_30d": 8,
        "growth_intent_level": 2,
        "positioning_line": "bowel-prep clarity",
        "bio_emails": ["jane@clinic.co.uk"],
        "bio_links": [{"url": "https://jane.clinic", "class": "own_site"}],
        "score_breakdown": {"growth_intent": 20},
        "deep_status": "none",
    }
    row.update(extra)
    return row


def test_promote_source_does_not_create_clinic_accounts():
    src = inspect.getsource(promote_mod.promote_creators) + inspect.getsource(promote_mod.promote_one)
    assert "find_or_create_clinic_account(" not in src
    assert '.table("clinic_accounts")' not in src
    assert ".table('clinic_accounts')" not in src


def test_eligible_requires_confirmed_gb_customer():
    assert eligible(_profile()) is True
    assert eligible(_profile(do_not_contact=True)) is False
    assert eligible(_profile(review_status="pending")) is False
    assert eligible(_profile(lane="research")) is False
    assert eligible(_profile(geo_country="US")) is False


def test_promote_calls_upsert_clinic_intelligence(monkeypatch):
    seen = []

    def fake_upsert(row, dry_run=False):
        seen.append(row)
        return {"id": "cl-new", "dry_run": dry_run, **row}

    people = []

    def fake_people(clinic_id, rows, dry_run=False, clinic_account_id=None):
        people.append({"clinic_id": clinic_id, "rows": rows, "dry_run": dry_run})
        return len(rows)

    monkeypatch.setattr(promote_mod, "upsert_clinic_intelligence", fake_upsert)
    monkeypatch.setattr(promote_mod, "upsert_clinic_people", fake_people)
    monkeypatch.setattr(promote_mod, "supabase_configured", lambda: True)

    client = FakeClient(
        {
            "gtm_clinic_intelligence": [],
            "integrated_practitioners": [],
            "creator_peer_briefs": [],
            "creator_links": [],
            "gtm_clinic_people": [],
            "gtm_outreach_contacts": [],
            "creator_profiles": [],
        }
    )
    profile = _profile()
    out = promote_creators(
        profiles=[profile],
        client=client,
        links_by_profile={profile["id"]: []},
        dry_run=True,
        refresh=False,
    )
    assert out["promoted"] == 1
    assert seen
    payload = seen[0]
    assert payload["source_creator_profile_id"] == "p1"
    assert payload["visible_clinic_size"] == "solo"
    assert payload["website_url"] == "https://jane.clinic"
    assert payload["specialties"] == ["colorectal"]
    assert payload["provenance"]["source"] == "creator_corpus"
    assert payload["provenance"]["lane"] == "tiktok_creator"
    assert people[0]["rows"][0]["creator_profile_id"] == "p1"
    assert people[0]["rows"][0]["social_profiles"]["tiktok"] == "drjane"
    assert people[0]["rows"][0]["role"] == "founder"


def test_promote_idempotent_lookup_by_source_creator(monkeypatch):
    seen = []

    def fake_upsert(row, dry_run=False):
        seen.append(row)
        return {"id": row.get("id") or "cl-existing", **row}

    monkeypatch.setattr(promote_mod, "upsert_clinic_intelligence", fake_upsert)
    monkeypatch.setattr(promote_mod, "upsert_clinic_people", lambda *a, **k: 1)
    monkeypatch.setattr(promote_mod, "supabase_configured", lambda: True)

    client = FakeClient(
        {
            "gtm_clinic_intelligence": [
                {
                    "id": "cl-existing",
                    "clinic_name": "Jane Clinic",
                    "website_url": "https://jane.clinic",
                    "source_creator_profile_id": "p1",
                    "doctify_url": None,
                }
            ],
            "integrated_practitioners": [],
            "creator_peer_briefs": [],
            "creator_links": [],
            "gtm_clinic_people": [
                {
                    "id": "pe1",
                    "clinic_intelligence_id": "cl-existing",
                    "full_name": "Dr Jane Smith",
                    "creator_profile_id": "p1",
                    "email": "jane@clinic.co.uk",
                    "social_profiles": {"tiktok": "drjane"},
                }
            ],
            "gtm_outreach_contacts": [],
            "creator_profiles": [],
        }
    )
    out = promote_creators(
        profiles=[_profile()],
        client=client,
        links_by_profile={"p1": []},
        dry_run=True,
        refresh=False,
    )
    assert out["results"][0]["clinic_intelligence_id"] == "cl-existing"
    assert out["results"][0]["clinic_resolution"] == "source_creator_profile_id"
    assert seen[0]["id"] == "cl-existing"
    assert "clinic_name" not in seen[0]


def test_name_only_link_not_used_unless_confirmed():
    profile = _profile()
    clinic_id, how = promote_mod.resolve_clinic_id(
        profile,
        [
            {
                "target_table": "gtm_clinic_intelligence",
                "target_id": "cl-name",
                "method": "name_only",
                "status": "suggested",
            }
        ],
        clinics_by_id={"cl-name": {"id": "cl-name"}},
        clinics_by_domain={},
        practitioners_by_id={},
    )
    assert clinic_id is None
    assert how == "insert_solo"


def test_tiktok_creator_angle_shape():
    item = tiktok_creator_angle(_profile(), brief_exists=True)
    assert item["kind"] == "tiktok_creator_angle"
    assert item["value"]["handle"] == "drjane"
    assert item["value"]["l3_brief_exists"] is True
    assert item["source"] == "creator_corpus"
