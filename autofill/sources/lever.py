"""Lever's public postings API -- no auth, one GET per company slug."""

from __future__ import annotations

import requests

from ..models import JobPosting
from ._util import strip_html

API_URL = "https://api.lever.co/v0/postings/{company}?mode=json"


def fetch_postings(company: str, timeout: float = 15.0) -> list[JobPosting]:
    resp = requests.get(API_URL.format(company=company), timeout=timeout)
    if resp.status_code != 200:
        print(f"[lever] {company}: HTTP {resp.status_code}, skipping")
        return []
    data = resp.json()
    postings = []
    for job in data:
        blurb = job.get("descriptionPlain") or strip_html(job.get("description", ""))
        categories = job.get("categories") or {}
        postings.append(
            JobPosting(
                source="lever",
                company=company,
                title=job.get("text", ""),
                url=job.get("hostedUrl", ""),
                location=categories.get("location", ""),
                blurb=blurb[:280],
                external_id=str(job.get("id", "")),
            )
        )
    return postings
