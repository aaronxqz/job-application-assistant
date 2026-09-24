"""Greenhouse's public job-board API -- no auth, one GET per company token."""

from __future__ import annotations

import requests

from ..models import JobPosting
from ._util import strip_html

API_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"


def fetch_postings(company_token: str, timeout: float = 15.0) -> list[JobPosting]:
    resp = requests.get(API_URL.format(token=company_token), timeout=timeout)
    if resp.status_code != 200:
        print(f"[greenhouse] {company_token}: HTTP {resp.status_code}, skipping")
        return []
    data = resp.json()
    postings = []
    for job in data.get("jobs", []):
        postings.append(
            JobPosting(
                source="greenhouse",
                company=company_token,
                title=job.get("title", ""),
                url=job.get("absolute_url", ""),
                location=(job.get("location") or {}).get("name", ""),
                blurb=strip_html(job.get("content", "")),
                external_id=str(job.get("id", "")),
            )
        )
    return postings
