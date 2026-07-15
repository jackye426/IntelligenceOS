"""Tests for CQC directory refresh helpers (no live download)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from gtm_pipeline.cqc_directory.refresh import (
    directory_status,
    download_directory,
    find_directory_csv_url,
    needs_refresh,
)


def test_find_directory_csv_url_parses_transparency_html():
    html = (
        '<a href="https://www.cqc.org.uk/sites/default/files/2024-01/'
        'CQC_directory.csv">Download</a>'
    )
    session = MagicMock()
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status = MagicMock()
    session.get.return_value = resp
    url = find_directory_csv_url(session=session)
    assert url.endswith("CQC_directory.csv")


def test_needs_refresh_missing(tmp_path: Path):
    assert needs_refresh(tmp_path / "missing.csv", max_age=7) is True


def test_needs_refresh_fresh(tmp_path: Path):
    p = tmp_path / "cqc_directory.csv"
    p.write_bytes(b"x" * 2000)
    assert needs_refresh(p, max_age=7) is False


def test_download_skips_when_fresh(tmp_path: Path):
    p = tmp_path / "cqc_directory.csv"
    p.write_bytes(b"x" * 2000)
    with patch(
        "gtm_pipeline.cqc_directory.refresh.find_directory_csv_url"
    ) as find:
        status = download_directory(p, force=False)
        find.assert_not_called()
    assert status.exists is True
    assert status.refreshed is False


def test_directory_status_shape(tmp_path: Path):
    st = directory_status(tmp_path / "nope.csv")
    assert st.exists is False
    assert st.needs_refresh is True
    d = st.as_dict()
    assert "path" in d
