"""Refuse GTM scripts that try to shell into Clinic sales agent (OG)."""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]  # Intelligence OS repo root
_OG = _REPO / "Clinic sales agent"


def assert_not_clinic_sales_path(path: Path | str) -> None:
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(_OG.resolve())
    except ValueError:
        return
    raise RuntimeError(
        f"GTM must not use Clinic sales agent path: {resolved}. "
        "Use gtm_pipeline doctify / cqc modules instead."
    )


def assert_command_not_og(argv: list[str]) -> None:
    blob = " ".join(argv).replace("\\", "/").lower()
    needles = (
        "clinic sales agent",
        "doctify_scraper",
        "cqc_lookup.py",
        "/src/main.py",
    )
    for n in needles:
        if n in blob:
            raise RuntimeError(f"GTM command refused (OG reference {n!r}): {argv}")
