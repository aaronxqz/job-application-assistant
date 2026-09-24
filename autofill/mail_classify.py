"""Matches recent emails to tracked applications and classifies them into a
status update, using keyword rules -- no API key, runs standalone via cron
same as `search`. Deliberately conservative: only acts on a clear keyword
signal for an email that already matches a tracked company; anything murkier
is left alone and surfaced for you to read yourself, same "don't guess"
philosophy as the rest of this tool.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from .tracking import LogEntry

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SEEN_AMBIGUOUS_PATH = REPO_ROOT / "data" / "mail_seen.json"


def load_seen_ambiguous(path: pathlib.Path | None = None) -> set[str]:
    """Gmail message IDs already shown once as "ambiguous, read yourself" --
    mail-check won't print these again on a later run within the same
    --query date window. Gmail's message id is stable per message, so this
    survives across runs even though the search window re-fetches the same
    messages every time.
    """
    path = path or SEEN_AMBIGUOUS_PATH
    if not path.exists():
        return set()
    return set(json.loads(path.read_text()))


def save_seen_ambiguous(seen: set[str], path: pathlib.Path | None = None) -> None:
    path = path or SEEN_AMBIGUOUS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(seen)))


COMPANY_MATCH_THRESHOLD = 85  # partial_ratio -- company names are distinctive
# enough (unlike short generic words) that this is safe at a high threshold.

# Account/portal mechanics, not application status -- confirmed on real
# mail: a Greenhouse "security code for your application" (a one-time
# verification code for the applicant PORTAL account) matched a "Cloud
# Security Engineer" posting purely because "security" appears in both, and
# a Gmail "Recovery phone was changed" account-security alert matched a
# "Google"-company posting purely because it mentions Google. Neither has
# anything to do with a specific application's status -- filtered out
# before company matching even runs, not just left ambiguous.
NON_APPLICATION_MARKERS = [
    "security code", "verification code", "one-time code", "one time code", "otp",
    "confirm your email", "verify your email", "please verify",
    "security alert", "recovery phone", "recovery email", "new sign-in",
    "suspicious activity", "password changed", "password reset",
    "verify it's you", "sign-in attempt", "account was accessed",
]


def is_non_application_email(subject: str, snippet: str) -> bool:
    text = f"{subject} {snippet}".lower()
    return any(marker in text for marker in NON_APPLICATION_MARKERS)

# Checked in this order -- rejection phrasing is checked first since some
# rejection emails also contain "thank you for applying", which would
# otherwise look like a confirmation.
CLASSIFY_RULES: list[tuple[str, list[str]]] = [
    (
        "rejected",
        [
            "unfortunately",
            "not moving forward",
            "will not be moving forward",
            "decided not to move forward",
            "other candidates",
            "not selected",
            "not be proceeding",
            "pursue other candidates",
            "position has been filled",
        ],
    ),
    (
        "offer",
        ["pleased to offer", "offer of employment", "extend an offer", "job offer"],
    ),
    (
        "interview",
        [
            "schedule a call",
            "schedule an interview",
            "would like to speak",
            "next steps",
            "meet with you",
            "chat with you",
            "phone screen",
            "interview invitation",
            "book a time",
        ],
    ),
    (
        "applied",
        [
            "received your application",
            "thank you for applying",
            "thanks for applying",
            "thanks so much for submitting",
            "thank you for submitting",
            "submitting your application",
            "application received",
            "confirming your application",
            "we've received your",
            "thank you for your interest in",
            "we appreciate your interest in",
        ],
    ),
]


def classify_email(subject: str, snippet: str) -> str | None:
    text = f"{subject} {snippet}".lower()
    for status, phrases in CLASSIFY_RULES:
        if any(phrase in text for phrase in phrases):
            return status
    return None


def match_company(message: dict[str, Any], entries: list[LogEntry]) -> LogEntry | None:
    """Finds the tracked entry this message is about.

    Company name alone isn't enough -- confirmed on real mail: two Stripe
    confirmation emails (different roles) had the *identical* subject
    ("Thanks for applying to Stripe!"), and the role name only showed up in
    the snippet. Company-only matching silently picked whichever Stripe
    entry came first for both, misattributing the second one -- so this
    also scores role-word overlap (also against the snippet, not just
    subject) and uses that to disambiguate between multiple postings at the
    same company; company match alone is the fallback when no role text is
    present to break the tie.
    """
    text = f"{message.get('from', '')} {message.get('subject', '')} {message.get('snippet', '')}".lower()

    candidates = []
    for entry in entries:
        if not entry.company:
            continue
        company_score = fuzz.partial_ratio(entry.company.lower(), text)
        if company_score >= COMPANY_MATCH_THRESHOLD:
            role_score = fuzz.token_set_ratio(entry.role.lower(), text) if entry.role else 0.0
            candidates.append((entry, role_score, company_score))

    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[1], c[2]), reverse=True)
    return candidates[0][0]


@dataclass
class MailCheckResult:
    updated: list[tuple[LogEntry, str, dict]] = None  # (entry, new_status, message)
    ambiguous: list[tuple[LogEntry, dict]] = None  # (entry, message) -- matched company, no clear status

    def __post_init__(self):
        self.updated = self.updated or []
        self.ambiguous = self.ambiguous or []
