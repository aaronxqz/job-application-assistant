"""Heuristics for matching a form field's label text to a profile value.

The core problem: every site phrases the same question differently
("First Name" vs "Legal first name" vs "Given name(s)"). Rather than
hardcoding per-site selectors for every possible field, we keep a table
of (profile path -> phrases people use for it) and fuzzy-match the
form's actual label text against those phrases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .profile import Profile

MATCH_THRESHOLD = 78  # 0-100, rapidfuzz token_set_ratio score to accept a match

_PUNCT_RE = re.compile(r"[/\-|]")
_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-z0-9]+")


def _normalize(s: str) -> str:
    s = _PUNCT_RE.sub(" ", s.strip().lower())
    return _WS_RE.sub(" ", s).strip()


def _words(s: str) -> set[str]:
    return set(_WORD_RE.findall(s.lower()))


def _score(label_norm: str, alias: str) -> float:
    """token_set_ratio handles fuzzy paraphrasing well, but structurally
    under-scores a short alias that's exactly, wholly present inside a much
    longer label (e.g. "city" inside "Location (City)*" scores ~40 despite
    being a perfect match) -- so also check whether every alias word appears
    as a whole word in the label, and treat that as a full-confidence match.
    This is deliberately whole-word, not substring: it's what keeps this
    safe from the original bug (partial_ratio matching "state" inside
    "status" by character overlap) -- "state" as an exact word is not
    present in "veteran status", so it still correctly stays unmatched.

    A whole-word-subset match scores 90-100, not a flat 100, weighted by
    how much of the label the alias actually covers -- otherwise two
    different specs whose aliases both subset-match the same label (e.g.
    "degree" for education.degree vs "degree level" for
    education.degree_level, against label "Degree Level") tie at 100 and
    the wrong one wins by table order. Coverage-weighting makes the more
    complete/specific alias score higher and win outright. Every subset
    match still clears MATCH_THRESHOLD (78) on its own, so this can't
    regress a previously-passing single-candidate match.
    """
    alias_norm = _normalize(alias)
    alias_words, label_words = _words(alias_norm), _words(label_norm)
    if alias_words and alias_words.issubset(label_words):
        coverage = len(alias_words) / len(label_words)
        return 90.0 + 10.0 * coverage
    return fuzz.token_set_ratio(label_norm, alias_norm)


@dataclass
class FieldSpec:
    profile_path: str
    aliases: list[str] = field(default_factory=list)
    kind: str = "text"  # text | select | checkbox | file


FIELD_TABLE: list[FieldSpec] = [
    FieldSpec("personal.first_name", ["first name", "given name", "legal first name"]),
    FieldSpec("personal.last_name", ["last name", "surname", "family name", "legal last name"]),
    FieldSpec("personal.email", ["email", "e-mail address"]),
    FieldSpec("personal.phone", ["phone", "mobile", "telephone", "contact number"]),
    FieldSpec("personal.address_line1", ["address", "street address", "address line 1"]),
    FieldSpec("personal.city", ["city", "town"]),
    FieldSpec("personal.state", ["state", "province", "region"], kind="select"),
    FieldSpec("personal.zip", ["zip", "postal code", "zip code"]),
    FieldSpec("personal.country", ["country"], kind="select"),
    FieldSpec("personal.linkedin_url", ["linkedin", "linkedin profile", "linkedin url"]),
    FieldSpec("personal.github_url", ["github", "github profile", "github url"]),
    FieldSpec("personal.portfolio_url", ["portfolio", "website", "personal website"]),
    FieldSpec(
        "work_authorization.authorized_to_work_in_us",
        ["authorized to work", "legally authorized", "work authorization"],
        kind="checkbox",
    ),
    FieldSpec(
        "work_authorization.requires_sponsorship_now_or_future",
        ["require sponsorship", "visa sponsorship", "sponsorship now or in the future"],
        kind="checkbox",
    ),
    FieldSpec("education.school", ["school", "university", "college"]),
    FieldSpec("education.degree", ["degree", "major", "field of study"]),
    FieldSpec(
        "education.degree_level",
        ["degree level", "degree type", "level of education", "highest degree earned"],
    ),
    FieldSpec("education.graduation_date", ["graduation date", "expected graduation"]),
    FieldSpec("education.gpa", ["gpa", "grade point average"]),
    FieldSpec("experience_years.total", ["years of experience", "total years of experience"]),
    FieldSpec("common_answers.why_interested", ["why are you interested", "why do you want to work"]),
    FieldSpec("common_answers.salary_expectation", ["salary expectation", "desired salary", "compensation expectation"]),
    FieldSpec("common_answers.start_date", ["available start date", "when can you start", "start date"]),
    FieldSpec("common_answers.willing_to_relocate", ["willing to relocate", "open to relocation"]),
    FieldSpec("common_answers.security_clearance", ["security clearance", "hold a clearance"]),
    FieldSpec("resume.file_path", ["resume", "cv", "upload resume"], kind="file"),
    FieldSpec("resume.cover_letter_path", ["cover letter"], kind="file"),
]


def best_match(label_text: str, profile: Profile) -> tuple[FieldSpec, str] | None:
    """Return (FieldSpec, value_as_string) for the best-scoring field, or None.

    Uses token_set_ratio, not partial_ratio: partial_ratio scores based on
    the best-aligned substring, which makes short generic aliases (e.g.
    "state", "phone") prone to high-scoring false positives against long,
    unrelated labels purely by character overlap -- confirmed in practice on
    a real Stripe form, where "Veteran Status" matched personal.state and a
    sponsorship question matched personal.phone, both above the old
    threshold. token_set_ratio compares actual token overlap instead, which
    eliminates that class of false positive (verified against a regression
    set of the true/false matches this table needs to get right) at the
    cost of occasionally missing a real match that's a short alias buried in
    a long sentence -- an acceptable tradeoff, since a missed match falls
    through to "skipped, fill by hand" rather than a wrong answer.
    """
    if not label_text or not label_text.strip():
        return None
    label_norm = _normalize(label_text)

    best_spec: FieldSpec | None = None
    best_score = 0.0
    for spec in FIELD_TABLE:
        for alias in spec.aliases:
            score = _score(label_norm, alias)
            if score > best_score:
                best_score = score
                best_spec = spec

    if best_spec is None or best_score < MATCH_THRESHOLD:
        return None

    value = profile.get(best_spec.profile_path)
    if value is None or value == "":
        return None
    return best_spec, str(value)
