"""Tests for scraper/slot_extractor.py — offline, no Playwright needed."""

from datetime import datetime, timezone

import pytest

from scraper.slot_extractor import _parse_datetime_to_utc, extract_from_api
from scraper.network_interceptor import CandidateEndpoint


def make_endpoint(response_json) -> CandidateEndpoint:
    return CandidateEndpoint(
        url="https://booking.hcahealthcare.co.uk/api/slots",
        method="GET",
        query_params={},
        request_body=None,
        response_status=200,
        response_json=response_json,
        timing_ms=120.0,
        looks_like_slots=True,
    )


COMMON_ARGS = dict(
    consultant_id=1,
    consultant_name="Michael Adamczyk",
    profile_url="https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/michael-adamczyk",
    location_name="The Lister Hospital",
    appointment_type="initial",
    funding_route="self-pay",
)


class TestParseDatetimeToUtc:
    def test_iso_string_with_tz(self):
        dt = _parse_datetime_to_utc("2025-06-15T09:00:00+01:00")
        assert dt is not None
        assert dt.tzinfo == timezone.utc
        assert dt.hour == 8  # BST +1 → UTC

    def test_iso_string_no_tz_assumes_london(self):
        # During BST (summer), 09:00 London = 08:00 UTC
        dt = _parse_datetime_to_utc("2025-07-10T09:00:00")
        assert dt is not None
        assert dt.tzinfo == timezone.utc

    def test_unix_timestamp_seconds(self):
        ts = 1750000000  # ~2025-06-15
        dt = _parse_datetime_to_utc(ts)
        assert dt is not None
        assert dt.tzinfo == timezone.utc

    def test_unix_timestamp_milliseconds(self):
        ts = 1750000000000  # milliseconds
        dt = _parse_datetime_to_utc(ts)
        assert dt is not None
        assert dt.tzinfo == timezone.utc

    def test_invalid_returns_none(self):
        assert _parse_datetime_to_utc("not-a-date") is None
        assert _parse_datetime_to_utc("") is None


class TestExtractFromApi:
    def test_list_format(self):
        data = [
            {"startTime": "2025-07-01T10:00:00+01:00", "available": True, "price": 250},
            {"startTime": "2025-07-01T11:00:00+01:00", "available": True},
        ]
        slots = extract_from_api(make_endpoint(data), **COMMON_ARGS)
        assert len(slots) == 2
        assert slots[0].slot_time == "10:00"
        assert slots[0].price == "250"

    def test_filters_unavailable_slots(self):
        data = [
            {"startTime": "2025-07-01T10:00:00+01:00", "available": True},
            {"startTime": "2025-07-01T11:00:00+01:00", "available": False},
            {"startTime": "2025-07-01T12:00:00+01:00", "isAvailable": False},
        ]
        slots = extract_from_api(make_endpoint(data), **COMMON_ARGS)
        assert len(slots) == 1

    def test_wrapped_format_slots_key(self):
        data = {"slots": [
            {"startTime": "2025-08-01T09:00:00Z", "available": True},
        ]}
        slots = extract_from_api(make_endpoint(data), **COMMON_ARGS)
        assert len(slots) == 1

    def test_wrapped_format_appointments_key(self):
        data = {"appointments": [
            {"start": "2025-08-01T14:00:00Z"},
        ]}
        slots = extract_from_api(make_endpoint(data), **COMMON_ARGS)
        assert len(slots) == 1

    def test_empty_response(self):
        slots = extract_from_api(make_endpoint([]), **COMMON_ARGS)
        assert slots == []

    def test_none_response(self):
        slots = extract_from_api(make_endpoint(None), **COMMON_ARGS)
        assert slots == []

    def test_slot_utc_storage(self):
        data = [{"startTime": "2025-06-15T09:00:00+01:00", "available": True}]
        slots = extract_from_api(make_endpoint(data), **COMMON_ARGS)
        assert slots[0].slot_datetime.tzinfo == timezone.utc
        assert slots[0].slot_date == "2025-06-15"
        assert slots[0].slot_time == "09:00"

    def test_slot_fields_populated(self):
        data = [{"startTime": "2025-09-01T10:00:00Z", "available": True}]
        slots = extract_from_api(make_endpoint(data), **COMMON_ARGS)
        s = slots[0]
        assert s.consultant_id == 1
        assert s.consultant_name == "Michael Adamczyk"
        assert s.location_name == "The Lister Hospital"
        assert s.appointment_type == "initial"
        assert s.funding_route == "self-pay"
        assert s.slot_timezone == "Europe/London"
