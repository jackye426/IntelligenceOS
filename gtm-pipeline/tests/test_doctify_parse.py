"""Offline Doctify specialist-card parsing (LOCKED selectors)."""

from __future__ import annotations

from gtm_pipeline.doctify.extract import parse_specialists_from_html
from gtm_pipeline.scoring import classify_visible_clinic_size, scan_leadership


SAMPLE_HTML = """
<html><body>
  <h1>London Gynaecology</h1>
  <a data-testid="specialist-link">25 specialists</a>
  <div data-testid="specialist-card">
    <a data-testid="specialist-name" href="/uk/specialist/dr-jane-doe">Dr Jane Doe</a>
    <div data-testid="specialist-specialty">Obstetrics &amp; Gynaecology</div>
  </div>
  <div data-testid="specialist-card">
    <a data-testid="specialist-name" href="/uk/specialist/mr-john-smith">Mr John Smith</a>
    <div data-testid="specialist-specialty">Fertility Medicine</div>
  </div>
  <p>Our clinic was established by the founder and medical director who leads a dedicated team.</p>
  <script id="__NEXT_DATA__" type="application/json">
  {"props":{"pageProps":{"practice":{
    "name":"London Gynaecology",
    "about":"Founded by our medical director to deliver specialist care.",
    "address":{"line1":"64 Harley Street","city":"London","postcode":"W1G 7HB"},
    "websiteUrl":"https://www.london-gynaecology.com",
    "email":"info@london-gynaecology.com",
    "phone":"02071234567",
    "specialties":[{"name":"Obstetrics & Gynaecology"}]
  }}}}
  </script>
</body></html>
"""


def test_parse_specialists_locked_selectors():
    result = parse_specialists_from_html(
        SAMPLE_HTML,
        doctify_url="https://www.doctify.com/uk/practice/london-gynaecology-harley-street",
    )
    assert result.listed_specialist_count == 25
    assert len(result.specialists) == 2
    assert result.specialists[0].name == "Dr Jane Doe"
    assert "specialist/dr-jane-doe" in result.specialists[0].profile_url
    assert result.clinic_name == "London Gynaecology"
    assert result.postcode == "W1G 7HB"
    assert result.website_url.startswith("https://www.london-gynaecology.com")
    assert result.email == "info@london-gynaecology.com"
    assert result.visible_clinic_size == "large"  # listed count 25
    assert "founder" in result.leadership_keywords or "medical_director" in result.leadership_keywords
    assert result.founder_score > 0


def test_visible_clinic_size_buckets():
    assert classify_visible_clinic_size(1) == "solo"
    assert classify_visible_clinic_size(3) == "micro"
    assert classify_visible_clinic_size(9) == "small"
    assert classify_visible_clinic_size(10) == "mid"
    assert classify_visible_clinic_size(25) == "large"


def test_leadership_scan():
    hit = scan_leadership("She is the co-founder and medical director of the practice.")
    assert hit is not None
    assert hit.role in {"founder", "medical_director"}
    assert "founder" in hit.keywords
