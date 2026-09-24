"""LinkedIn job search via the public (no-login-required) guest search page.

Deliberately reads only the first results page -- no scrolling/pagination --
and sleeps page_delay_ms before reading, so this behaves like one slow,
human-paced page load rather than a scrape burst. Selectors were confirmed
by live-inspecting linkedin.com/jobs/search/ -- if LinkedIn changes their
markup this will need re-inspecting, same as any scraper.
"""

from __future__ import annotations

from urllib.parse import quote

from playwright.sync_api import Page

from ..models import JobPosting

SEARCH_URL = "https://www.linkedin.com/jobs/search/?keywords={keywords}&location={location}"
CARD_SELECTOR = "div.base-card"


def search_jobs(
    page: Page,
    keywords: str,
    location: str = "United States",
    max_results: int = 25,
    page_delay_ms: int = 3000,
) -> list[JobPosting]:
    url = SEARCH_URL.format(keywords=quote(keywords), location=quote(location))
    page.goto(url, timeout=30000)
    page.wait_for_timeout(page_delay_ms)

    postings: list[JobPosting] = []
    cards = page.locator(CARD_SELECTOR)
    count = min(cards.count(), max_results)
    for i in range(count):
        card = cards.nth(i)
        try:
            title = card.locator("h3.base-search-card__title").inner_text().strip()
            company = card.locator("h4.base-search-card__subtitle a").inner_text().strip()
            job_url = card.locator("a.base-card__full-link").first.get_attribute("href") or ""
            location_text = ""
            loc_locator = card.locator("span.job-search-card__location")
            if loc_locator.count() > 0:
                location_text = loc_locator.first.inner_text().strip()
        except Exception:
            continue
        if not job_url:
            continue
        postings.append(
            JobPosting(
                source="linkedin",
                company=company,
                title=title,
                url=job_url.split("?")[0],
                location=location_text,
                blurb="",
            )
        )
    return postings
