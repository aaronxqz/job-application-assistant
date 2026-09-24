"""Auto-tags a posting with a category and employment type for the tracking
log / dashboard. Same rapidfuzz-keyword-table shape as relevance.py. These
are starting guesses -- hand-edit the CSV afterward if one guessed wrong.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from .models import JobPosting

CATEGORY_THRESHOLD = 60
TYPE_THRESHOLD = 60

CATEGORY_RULES: dict[str, list[str]] = {
    "SDE": ["software engineer", "software developer", "sde", "swe", "backend", "frontend", "full stack"],
    "SRE": ["site reliability", "sre", "reliability engineer", "devops", "platform engineer", "infrastructure engineer"],
    "Security": ["security", "cybersecurity", "infosec", "soc analyst"],
    "IT": [
        "it support", "help desk", "desktop support", "it technician",
        "systems administrator", "system administrator", "sysadmin",
        "administrative", "administrative assistant", "office administrator",
    ],
    "Data": ["data analyst", "data engineer", "data scientist"],
}
DEFAULT_CATEGORY = "Other"

TYPE_RULES: dict[str, list[str]] = {
    "Internship": ["intern", "internship", "co-op"],
    "Entry Level": ["entry level", "entry-level", "new grad", "junior", "associate"],
}
DEFAULT_TYPE = "Full Time"


def _best_label(text: str, rules: dict[str, list[str]], threshold: int, default: str) -> str:
    best_label = default
    best_score = 0.0
    for label, phrases in rules.items():
        for phrase in phrases:
            score = fuzz.token_set_ratio(text, phrase)
            if score > best_score:
                best_score = score
                best_label = label
    if best_score < threshold:
        return default
    return best_label


def classify(posting: JobPosting) -> tuple[str, str]:
    text = f"{posting.title} {posting.blurb}".strip().lower()
    category = _best_label(text, CATEGORY_RULES, CATEGORY_THRESHOLD, DEFAULT_CATEGORY)
    employment_type = _best_label(text, TYPE_RULES, TYPE_THRESHOLD, DEFAULT_TYPE)
    return category, employment_type
