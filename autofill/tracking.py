"""CSV-backed application tracking log at applied_log.csv (repo root).

One row per job posting, deduped by URL. Whole-file read/rewrite per update
-- fine for a single-user local CLI tool, and the file is plain CSV so it
opens directly in Excel/Sheets/Numbers too, not just through this tool.
"""

from __future__ import annotations

import csv
import pathlib
import re
from dataclasses import asdict, dataclass, fields
from datetime import date

from .classify import classify
from .location import classify_location
from .models import JobPosting

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
LOG_PATH = REPO_ROOT / "applied_log.csv"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(*parts: str) -> str:
    """company + role -> a filesystem-safe slug, e.g. "stripe-ai-engineer".
    Used to name per-posting cover letter files so `review` can find one
    you (or Claude, when asked) saved for a specific application.
    """
    text = " ".join(p for p in parts if p)
    return _SLUG_RE.sub("-", text.lower()).strip("-")

SUPPORTED_FILL_SOURCES = {"greenhouse", "lever", "linkedin"}

STATUSES = (
    "found",
    "queued",
    "pending",  # review touched it but couldn't confirm it's actually complete -- needs a manual look
    "filled_pending_review",
    "applied",
    "interview",
    "rejected",
    "offer",
    "abandoned",  # you decided not to pursue this one -- excluded from the review queue and needs_manual_apply
)

FIELDNAMES = [
    "url",
    "company",
    "role",
    "category",
    "employment_type",
    "location",
    "location_type",
    "source",
    "status",
    "blurb",
    "found_at",
    "applied_at",
    "updated_at",
    "unmatched_fields",
]


@dataclass
class LogEntry:
    url: str
    company: str
    role: str
    category: str = ""
    employment_type: str = ""
    location: str = ""  # raw text from the source, e.g. "San Francisco, CA"
    location_type: str = ""  # "Remote" | Northeast/Midwest/South/West | "US - Unspecified" | "Non-US" | "Unknown"
    source: str = ""
    status: str = "found"
    blurb: str = ""
    found_at: str = ""
    applied_at: str = ""
    updated_at: str = ""
    unmatched_fields: str = ""


def _today() -> str:
    return date.today().isoformat()


def load_log(path: pathlib.Path | None = None) -> list[LogEntry]:
    path = path or LOG_PATH
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        valid_fields = {f.name for f in fields(LogEntry)}
        return [LogEntry(**{k: v for k, v in row.items() if k in valid_fields}) for row in reader]


def save_log(entries: list[LogEntry], path: pathlib.Path | None = None) -> None:
    path = path or LOG_PATH
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for entry in entries:
            writer.writerow(asdict(entry))


def upsert_found(postings: list[JobPosting], path: pathlib.Path | None = None) -> tuple[int, int, int]:
    """Returns (added, already_tracked, auto_abandoned) -- auto_abandoned is
    how many of the newly-added postings were immediately marked abandoned
    for being Non-US (see autofill/location.py); they're still added as a
    row (so search never re-considers that URL again) but start at
    status="abandoned" instead of "found".
    """
    entries = load_log(path)
    existing_urls = {e.url for e in entries}
    added = 0
    already_tracked = 0
    auto_abandoned = 0
    today = _today()
    for posting in postings:
        if posting.url in existing_urls:
            already_tracked += 1
            continue
        category, employment_type = classify(posting)
        location_type, should_abandon = classify_location(posting.location, posting.blurb)
        if should_abandon:
            auto_abandoned += 1
        entries.append(
            LogEntry(
                url=posting.url,
                company=posting.company,
                role=posting.title,
                category=category,
                employment_type=employment_type,
                location=posting.location,
                location_type=location_type,
                source=posting.source,
                status="abandoned" if should_abandon else "found",
                blurb=posting.blurb,
                found_at=today,
                updated_at=today,
            )
        )
        existing_urls.add(posting.url)
        added += 1
    save_log(entries, path)
    return added, already_tracked, auto_abandoned


def update_status(
    url: str,
    status: str,
    *,
    unmatched_fields: str | None = None,
    path: pathlib.Path | None = None,
) -> None:
    entries = load_log(path)
    today = _today()
    for entry in entries:
        if entry.url != url:
            continue
        entry.status = status
        entry.updated_at = today
        if status == "applied" and not entry.applied_at:
            entry.applied_at = today
        if unmatched_fields is not None:
            entry.unmatched_fields = unmatched_fields
        break
    save_log(entries, path)


def _interleave_by_company(entries: list[LogEntry]) -> list[LogEntry]:
    """Round-robins across companies instead of exhausting one company's
    whole backlog before the next -- confirmed as a real problem: found_at
    only has day granularity, so a high-volume source (e.g. one company
    with 300+ postings found the same day) sorts as one unbroken block
    ahead of everyone else on a flat newest/oldest sort. Preserves each
    company's own relative order (already sorted by the caller); only
    changes which company's entries interleave with which.
    """
    groups: dict[str, list[LogEntry]] = {}
    company_order: list[str] = []
    for e in entries:
        if e.company not in groups:
            groups[e.company] = []
            company_order.append(e.company)
        groups[e.company].append(e)

    result: list[LogEntry] = []
    indices = {c: 0 for c in company_order}
    remaining = len(entries)
    while remaining:
        for c in company_order:
            i = indices[c]
            if i < len(groups[c]):
                result.append(groups[c][i])
                indices[c] = i + 1
                remaining -= 1
    return result


def preview_queue(
    path: pathlib.Path | None = None,
    sort: str = "newest",
    categories: list[str] | None = None,
    interleave: bool = True,
) -> list[LogEntry]:
    """All still-`found`/`queued` entries -- both fillable (Greenhouse/
    Lever/LinkedIn) and manual-apply-only (Amazon/Google/TikTok) -- in one
    unified order, for `review`'s pre-flight numbered list. This is the
    shared source of truth `entries_for_review` filters down from, so the
    order shown in the preview always matches what `review` actually walks
    through.

    sort: "newest" (default) or "oldest", by found_at.
    categories: if given, only entries whose category matches one of these
    (case-insensitive) -- e.g. ["IT", "SRE"].
    interleave: round-robin across companies (see _interleave_by_company)
    instead of a flat sort -- on by default since the flat sort is what
    caused one company's backlog to dominate the queue in practice.
    """
    entries = load_log(path)
    queue = [e for e in entries if e.status in ("found", "queued")]
    if categories:
        wanted = {c.lower() for c in categories}
        queue = [e for e in queue if e.category.lower() in wanted]
    queue.sort(key=lambda e: e.found_at, reverse=(sort != "oldest"))
    if interleave:
        queue = _interleave_by_company(queue)
    return queue


def entries_for_review(
    path: pathlib.Path | None = None,
    sort: str = "newest",
    categories: list[str] | None = None,
    interleave: bool = True,
) -> list[LogEntry]:
    queue = preview_queue(path, sort=sort, categories=categories, interleave=interleave)
    return [e for e in queue if e.source in SUPPORTED_FILL_SOURCES]


def needs_manual_apply(path: pathlib.Path | None = None) -> list[LogEntry]:
    entries = load_log(path)
    return [
        e for e in entries
        if e.status in ("found", "queued") and e.source not in SUPPORTED_FILL_SOURCES
    ]
