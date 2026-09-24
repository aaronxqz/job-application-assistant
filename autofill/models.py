"""Shared value object for job postings found by any search source."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class JobPosting:
    source: str  # "greenhouse" | "lever" | "linkedin" | "amazon" | "google" | "tiktok"
    company: str
    title: str
    url: str  # canonical apply URL -- dedup key in tracking.py
    location: str = ""
    blurb: str = ""  # short plain-text summary, for the tracking log's "quick refresh" column
    external_id: str = ""  # source's native job id
