"""Unit tests for Doctify listing URL helpers (no network)."""

from gtm_pipeline.doctify.listing import build_page_url, load_scope_csv


def test_build_page_url_page_1():
    base = "https://www.doctify.com/uk/find/endometriosis/harley-street/practices"
    assert build_page_url(base, 1) == base


def test_build_page_url_page_n():
    base = "https://www.doctify.com/uk/find/egg-freezing/harley-street/practices#distance=10"
    out = build_page_url(base, 3)
    assert "/practices/page-3" in out
    assert "distance=10" in out


def test_build_page_url_strips_existing_page():
    base = "https://www.doctify.com/uk/find/x/y/practices/page-2"
    assert build_page_url(base, 4).endswith("/practices/page-4")


def test_load_scope_csv(tmp_path):
    p = tmp_path / "scope.csv"
    p.write_text(
        "url,pages\nhttps://www.doctify.com/uk/find/a/b/practices,2\n\n",
        encoding="utf-8",
    )
    rows = load_scope_csv(p)
    assert len(rows) == 1
    assert rows[0]["pages"] == 2
