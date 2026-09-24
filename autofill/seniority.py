"""Detects postings that require meaningful prior experience -- senior/
staff/principal/manager-level roles, or anything whose JD explicitly states
a multi-year experience requirement -- so they can be excluded from the
review queue and from future `search` results.

Calibrated against real tracked data (not guessed): an earlier version of
the years-of-experience regex matched "18 years of **age**" on Amazon
internship postings (a legal eligibility line, unrelated to seniority) --
fixed by requiring the specific "years ... experience" phrasing. Title
keyword matching was checked against all 157 unique titles it flagged in
that same dataset with zero false positives.
"""

from __future__ import annotations

import re

SENIOR_TITLE_WORDS = [
    "senior", "sr.", "sr ", "staff", "principal", "lead ", " lead,",
    "director", "vp ", "vice president", "head of", "architect", "manager",
]
JUNIOR_OVERRIDE_WORDS = [
    "intern", "internship", "new grad", "entry level", "entry-level",
    "junior", "co-op", "associate",
]

# Requires the specific "N+ years ... experience" phrasing, not just any
# nearby number -- "18 years of age" (an eligibility line, common on
# internship postings) must NOT match.
YEARS_EXPERIENCE_RE = re.compile(
    r"(\d+)\+?\s*(?:-\s*\d+)?\s*\+?\s*years?\s+(?:of\s+)?"
    r"(?:relevant\s+|professional\s+|industry\s+|work\s+)?experience",
    re.IGNORECASE,
)
MIN_YEARS_THRESHOLD = 3


def required_years(text: str) -> int | None:
    """Lowest years-of-experience figure explicitly stated, or None."""
    years = [int(m.group(1)) for m in YEARS_EXPERIENCE_RE.finditer(text)]
    return min(years) if years else None


def is_senior(title: str, blurb: str = "") -> tuple[bool, str]:
    """Returns (is_senior, reason). A junior/intern/entry-level word in the
    TITLE always wins over any other signal (a "Senior Software Engineer
    Internship Program" isn't realistically a thing, but if a title
    contains both, trust the explicit level marker over inference).
    """
    title_lower = title.lower()
    if any(w in title_lower for w in JUNIOR_OVERRIDE_WORDS):
        return False, ""

    for w in SENIOR_TITLE_WORDS:
        if w in title_lower:
            return True, f'title contains "{w.strip()}"'

    years = required_years(f"{title} {blurb}")
    if years is not None and years >= MIN_YEARS_THRESHOLD:
        return True, f"requires {years}+ years of experience"

    return False, ""
