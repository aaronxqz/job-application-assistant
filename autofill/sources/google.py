"""Google Careers search -- no login required to search, only to apply.

Search-only: there is no fill adapter for careers.google.com yet (custom
application forms, needs live inspection first -- see NOTES.md/README.md
Phase 2). Postings from this adapter are tracked but `review` skips them.
"""

from __future__ import annotations

from urllib.parse import quote

from playwright.sync_api import Page

from ..models import JobPosting

BASE_URL = "https://www.google.com/about/careers/applications/"
SEARCH_URL = BASE_URL + "jobs/results?q={keywords}"
CARD_SELECTOR = "li.lLd3Je"


def search_jobs(
    page: Page,
    keywords: str,
    location: str = "United States",
    max_results: int = 25,
    page_delay_ms: int = 3000,
) -> list[JobPosting]:
    url = SEARCH_URL.format(keywords=quote(keywords))
    page.goto(url, timeout=30000)
    page.wait_for_timeout(page_delay_ms)

    postings: list[JobPosting] = []
    cards = page.locator(CARD_SELECTOR)
    count = min(cards.count(), max_results)
    for i in range(count):
        card = cards.nth(i)
        try:
            title = card.locator("h3.QJPWVe").inner_text().strip()
            href = card.locator("a.WpHeLc").first.get_attribute("href") or ""
            location_text = ""
            loc_locator = card.locator("span.r0wTof")
            if loc_locator.count() > 0:
                location_text = loc_locator.first.inner_text().strip()
            blurb = ""
            blurb_locator = card.locator("div.Xsxa1e")
            if blurb_locator.count() > 0:
                blurb = blurb_locator.inner_text().strip()[:280]
        except Exception:
            continue
        if not href:
            continue
        job_url = href if href.startswith("http") else BASE_URL + href
        postings.append(
            JobPosting(
                source="google",
                company="Google",
                title=title,
                url=job_url,
                location=location_text,
                blurb=blurb,
            )
        )
    return postings
