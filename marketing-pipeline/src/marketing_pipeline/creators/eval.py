"""Offline eval against a hand-labelled CSV. Gate before promotion."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from marketing_pipeline.creators.paths import normalise_handle
from marketing_pipeline.creators.store import get_store

GATES = {
    "is_doctor_precision": 0.95,
    "gb_precision": 0.90,
    "customer_lane_precision": 0.85,
}


def _precision(pairs: list[tuple[bool, bool]]) -> float | None:
    predicted_true = [actual for actual, predicted in pairs if predicted]
    if not predicted_true:
        return None
    return sum(1 for actual in predicted_true if actual) / len(predicted_true)


def run_eval(*, labels_path: Path, store=None) -> dict[str, Any]:
    store = store or get_store()
    profiles = {p.get("handle"): p for p in store.list("creator_profiles")}
    doctor_pairs: list[tuple[bool, bool]] = []
    gb_pairs: list[tuple[bool, bool]] = []
    customer_pairs: list[tuple[bool, bool]] = []
    missing = 0
    labelled = 0
    with labels_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            handle = normalise_handle(row.get("handle") or "")
            if not handle:
                continue
            labelled += 1
            profile = profiles.get(handle)
            if not profile:
                missing += 1
                continue
            labelled_doctor = str(row.get("is_doctor") or "").strip().lower() in {"1", "true", "yes"}
            predicted_doctor = bool(profile.get("is_doctor"))
            doctor_pairs.append((labelled_doctor, predicted_doctor))

            labelled_gb = str(row.get("geo_country") or "").strip().upper() == "GB"
            predicted_gb = (profile.get("geo_country") or "").upper() == "GB"
            gb_pairs.append((labelled_gb, predicted_gb))

            labelled_customer = str(row.get("lane") or "").strip() in {"customer", "both"}
            predicted_customer = profile.get("lane") in {"customer", "both"}
            customer_pairs.append((labelled_customer, predicted_customer))

    scores = {
        "is_doctor_precision": _precision(doctor_pairs),
        "gb_precision": _precision(gb_pairs),
        "customer_lane_precision": _precision(customer_pairs),
    }
    failed = [
        name
        for name, gate in GATES.items()
        if scores[name] is not None and scores[name] < gate
    ]
    return {
        "labels_path": str(labels_path),
        "labelled": labelled,
        "missing_profiles": missing,
        "scores": scores,
        "gates": GATES,
        "passed": not failed and labelled > 0 and missing < labelled,
        "failed_gates": failed,
    }
