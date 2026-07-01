"""
Tests for scraper/profile_extractor.py

These tests are stubs until sample_profile.html is saved from a live headful run.
Once the fixture exists, replace the placeholder HTML with the real saved content.

To save the fixture:
    python -c "
    import asyncio
    from playwright.async_api import async_playwright

    async def save():
        async with async_playwright() as pw:
            b = await pw.chromium.launch(headless=False)
            p = await b.new_page()
            await p.goto('https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/michael-adamczyk')
            with open('tests/fixtures/sample_profile.html', 'w', encoding='utf-8') as f:
                f.write(await p.content())
            await b.close()
    asyncio.run(save())
    "
"""

from scraper.profile_extractor import _parse_days_from_text


class TestParseDaysFromText:
    def test_full_day_names(self):
        days = _parse_days_from_text("Thursday 8am-5pm, Friday 1pm-7pm, Saturday 8am-7pm")
        assert "Thursday" in days
        assert "Friday" in days
        assert "Saturday" in days
        assert "Monday" not in days

    def test_abbreviated_names(self):
        days = _parse_days_from_text("Mon, Wed, Fri")
        assert "Monday" in days
        assert "Wednesday" in days
        assert "Friday" in days

    def test_empty_string(self):
        assert _parse_days_from_text("") == []

    def test_no_days(self):
        days = _parse_days_from_text("Available 9am to 5pm")
        assert days == []


# Placeholder: add fixture-based tests once sample_profile.html is saved
# class TestExtractProfileFromFixture:
#     def test_name_extracted(self, ...):
#         ...
