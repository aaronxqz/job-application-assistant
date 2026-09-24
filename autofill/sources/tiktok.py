"""TikTok/ByteDance careers search -- no login required to search, only to
apply. careers.tiktok.com/position redirects to lifeattiktok.com/search,
which is what this adapter targets directly.

Search-only: there is no fill adapter for lifeattiktok.com yet (custom
application forms, needs live inspection first -- see NOTES.md/README.md
Phase 2). Postings from this adapter are tracked but `review` skips them.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from playwright.sync_api import Page

from ..models import JobPosting

SEARCH_URL = "https://lifeattiktok.com/search?keyword={keywords}"
JOB_LINK_RE = re.compile(r"/search/\d+$")


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

    all_links = page.eval_on_selector_all("a[href*='/search/']", "els => els.map(e => e.getAttribute('href'))")
    job_urls = [h for h in all_links if JOB_LINK_RE.search(h)]
    job_urls = job_urls[:max_results]

    postings: list[JobPosting] = []
    for job_url in job_urls:
        try:
            card = page.locator(f"a[href='{job_url}']").first
            lines = [l.strip() for l in card.inner_text().split("\n") if l.strip()]
        except Exception:
            continue
        if not lines:
            continue
        title = lines[0]
        location_text = lines[1] if len(lines) > 1 else ""
        blurb = " | ".join(lines[1:])[:280]
        postings.append(
            JobPosting(
                source="tiktok",
                company="TikTok",
                title=title,
                url=job_url,
                location=location_text,
                blurb=blurb,
            )
        )
    return postings
