"""Offline Doctify specialist-card parsing (LOCKED selectors)."""

from __future__ import annotations

from gtm_pipeline.doctify.extract import (
    _format_address,
    _pick_website,
    _website_from_dom,
    parse_specialists_from_html,
)
from gtm_pipeline.scoring import classify_visible_clinic_size, scan_leadership


SAMPLE_HTML = """
<html><body>
  <h1>London Gynaecology</h1>
  <p>145 Harley St, London, United Kingdom, W1G 6BJ</p>
  <a href="https://www.london-gynaecology.com" target="_blank" rel="noopener">Visit our website</a>
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

I18N_ADDRESS_HTML = """
<html><body>
  <h1>I18n Clinic</h1>
  <a href="https://www.example-clinic.co.uk" target="_blank" rel="noopener">Website</a>
  <a data-testid="specialist-link">1 specialist</a>
  <div data-testid="specialist-card">
    <a data-testid="specialist-name" href="/uk/specialist/a">A</a>
    <div data-testid="specialist-specialty">Gynaecology</div>
  </div>
  <script id="__NEXT_DATA__" type="application/json">
  {"props":{"pageProps":{"practice":{
    "name":{"en":"I18n Clinic"},
    "address":[{"en":"145 Harley St"},{"en":"London"},{"en":"W1G 6BJ"}],
    "ContactDetails":[{"type":"website","url":"https://www.example-clinic.co.uk"}]
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


def test_i18n_address_list_and_contact_website():
    result = parse_specialists_from_html(
        I18N_ADDRESS_HTML,
        doctify_url="https://www.doctify.com/uk/practice/i18n-clinic",
    )
    assert "{'en'" not in result.address
    assert "Harley" in result.address
    assert result.postcode == "W1G 6BJ"
    assert result.website_url == "https://www.example-clinic.co.uk"
    assert result.clinic_name == "I18n Clinic"


def test_format_address_i18n_list():
    text, pc = _format_address([{"en": "London"}, {"en": "W1G 6BJ"}])
    assert text == "London, W1G 6BJ"
    assert pc == "W1G 6BJ"


def test_format_address_i18n_fields():
    text, pc = _format_address(
        {
            "line1": {"en": "64 Harley Street"},
            "city": {"en": "London"},
            "postcode": {"en": "W1G 7HB"},
        }
    )
    assert text == "64 Harley Street, London, W1G 7HB"
    assert pc == "W1G 7HB"


def test_pick_website_skips_doctify():
    assert _pick_website("https://www.doctify.com/uk/practice/x") == ""
    assert _pick_website("https://www.clinic.example") == "https://www.clinic.example"


def test_website_from_dom_prefers_labelled_link():
    html = '<a href="https://www.clinic.example" target="_blank">Visit our website</a>'
    assert _website_from_dom(html) == "https://www.clinic.example"


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
