"""Job search adapters. Each module exposes a function returning list[JobPosting].

collect_postings() is the single entry point cli.py's `search` command uses --
it runs Greenhouse/Lever (plain HTTP, always) and, if a browser page is
supplied, the four Playwright-based sources (LinkedIn/Amazon/Google/TikTok),
paced with a delay between every successive browser-based search so a
multi-source run doesn't turn into a burst.
"""

from __future__ import annotations

from typing import Any

from playwright.sync_api import Page

from ..models import JobPosting
from . import amazon, google, greenhouse, lever, linkedin_search, tiktok

_BROWSER_SOURCES = {
    "linkedin_searches": linkedin_search,
    "amazon_searches": amazon,
    "google_searches": google,
    "tiktok_searches": tiktok,
}


def collect_postings(search_config: dict[str, Any], page: Page | None = None) -> list[JobPosting]:
    postings: list[JobPosting] = []

    for token in search_config.get("greenhouse_tokens", []):
        postings.extend(greenhouse.fetch_postings(token))

    for company in search_config.get("lever_companies", []):
        postings.extend(lever.fetch_postings(company))

    if page is None:
        return postings

    rate_limit = search_config.get("rate_limit", {})
    max_results = rate_limit.get("browser_max_results_per_search", 25)
    page_delay_ms = rate_limit.get("browser_page_delay_ms", 3000)
    search_delay_ms = rate_limit.get("browser_search_delay_ms", 6000)

    first_search = True
    for config_key, module in _BROWSER_SOURCES.items():
        for entry in search_config.get(config_key, []):
            if not first_search:
                page.wait_for_timeout(search_delay_ms)
            first_search = False
            try:
                postings.extend(
                    module.search_jobs(
                        page,
                        keywords=entry.get("keywords", ""),
                        location=entry.get("location", "United States"),
                        max_results=max_results,
                        page_delay_ms=page_delay_ms,
                    )
                )
            except Exception as e:
                print(f"[{module.__name__.rsplit('.', 1)[-1]}] search failed: {e}")

    return postings
