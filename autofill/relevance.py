"""Loose "is this posting kinda related to me" filter.

Unlike field_matcher's exact label matching, this scores a whole title+blurb
against a list of loose phrases, so the threshold is deliberately lower.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from .models import JobPosting
from .profile import Profile

RELEVANCE_THRESHOLD = 60  # 0-100, looser than field_matcher.MATCH_THRESHOLD (78)


def build_keyword_list(profile: Profile, configured_keywords: list[str]) -> list[str]:
    keywords = list(configured_keywords)
    degree = profile.get("education.degree")
    if degree:
        keywords.append(str(degree))
    return keywords


def is_relevant(posting: JobPosting, keywords: list[str]) -> tuple[bool, float]:
    if not keywords:
        return True, 100.0
    text = f"{posting.title} {posting.blurb}".strip().lower()
    if not text:
        return False, 0.0

    best_score = 0.0
    for keyword in keywords:
        score = fuzz.token_set_ratio(text, keyword.lower())
        if score > best_score:
            best_score = score

    return best_score >= RELEVANCE_THRESHOLD, best_score
