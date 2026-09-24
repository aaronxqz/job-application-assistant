"""Command-line entry point.

Usage (from the project root, inside your activated venv):

    python -m autofill login                    # log into a site once; session is saved
    python -m autofill login https://linkedin.com/login
    python -m autofill fill <job-application-url>
    python -m autofill search                   # find + track new postings
    python -m autofill search --no-browser-search  # Greenhouse/Lever only, no browser
    python -m autofill review                    # fill queued postings, one at a time
    python -m autofill dashboard                  # live, editable dashboard (localhost server)
    python -m autofill dashboard --static           # one-shot static HTML file instead
    python -m autofill status --list               # list tracked postings with their index/status
    python -m autofill status <index> <new-status>  # manually correct one entry's status
    python -m autofill mail                        # list recent Gmail messages (read-only)
    python -m autofill mail-check                   # match mail to tracked apps, update statuses
"""

from __future__ import annotations

import argparse
import sys

import pathlib
from urllib.parse import urlparse

from .browser import open_persistent_context
from .classify import classify
from .dashboard import generate_and_open
from .dashboard_server import DEFAULT_PORT
from .dashboard_server import run as run_dashboard_server
from .mail_classify import (
    classify_email,
    is_non_application_email,
    load_seen_ambiguous,
    match_company,
    save_seen_ambiguous,
)
from .mailwatch import MailwatchError, authenticate, fetch_recent_messages
from .models import JobPosting
from .seniority import is_senior
from .platforms import get_filler_for_url
from .profile import ProfileError, load_profile
from .relevance import build_keyword_list, is_relevant
from .search_config import REPO_ROOT, SearchConfigError, load_search_config
from .sources import collect_postings
from .tracking import (
    STATUSES,
    SUPPORTED_FILL_SOURCES,
    load_log,
    needs_manual_apply,
    preview_queue,
    slugify,
    update_status,
    upsert_found,
)


def cmd_login(args: argparse.Namespace) -> None:
    context, pw = open_persistent_context(headless=False)
    page = context.new_page()
    page.goto(args.url or "https://www.linkedin.com/login")
    print("Log in manually in the browser window that just opened.")
    print("Once you're logged in, come back here and press Enter to close it.")
    print("(Your session is saved in browser_profile/ and will persist for future runs.)")
    input()
    context.close()
    pw.stop()


def cmd_fill(args: argparse.Namespace) -> None:
    try:
        profile = load_profile()
    except ProfileError as e:
        print(str(e))
        sys.exit(1)

    context, pw = open_persistent_context(headless=False)
    page = context.new_page()
    page.goto(args.url)
    page.wait_for_load_state("domcontentloaded")

    filler = get_filler_for_url(args.url)
    result = filler(page, profile)
    print(result.report())

    if not args.no_track:
        company = args.company or urlparse(args.url).netloc.removeprefix("www.").split(".")[0]
        try:
            role = args.role or page.title()
        except Exception:
            role = args.role or "(unknown role)"
        posting = JobPosting(source="manual", company=company, title=role, url=args.url, blurb="")
        upsert_found([posting])

        existing_status = next((e.status for e in load_log() if e.url == args.url), "found")
        if _STATUS_RANK.get("filled_pending_review", 0) >= _STATUS_RANK.get(existing_status, 0):
            update_status(args.url, "filled_pending_review", unmatched_fields="; ".join(result.skipped))
        # else: this URL was already further along (applied/interview/etc.) --
        # re-filling it (e.g. to double-check something) must never regress
        # that back down, same rule as mail-check.

        print(
            f"\nAdded to applied_log.csv as {company!r} -- {role!r} (best-effort guess from the "
            f"URL/page title -- correct it with `python -m autofill status --list` if it's off)."
        )

    print("\nDone. The browser window stays open -- fix anything the matcher")
    print("missed, double-check everything, and submit yourself when ready.")
    input("Press Enter here to close the browser...")
    context.close()
    pw.stop()


def cmd_search(args: argparse.Namespace) -> None:
    try:
        profile = load_profile()
    except ProfileError as e:
        print(str(e))
        sys.exit(1)

    try:
        config = load_search_config(args.config)
    except SearchConfigError as e:
        print(str(e))
        sys.exit(1)

    context = None
    pw = None
    page = None
    if not args.no_browser_search:
        context, pw = open_persistent_context(headless=False)
        page = context.new_page()

    try:
        postings = collect_postings(config, page=page)
    finally:
        if context is not None:
            context.close()
            pw.stop()

    keywords = build_keyword_list(profile, config.get("keywords", []))
    relevant = [p for p in postings if is_relevant(p, keywords)[0]]

    exclude_senior = config.get("exclude_senior", True)
    senior_count = 0
    if exclude_senior:
        kept = []
        for p in relevant:
            senior, _ = is_senior(p.title, p.blurb)
            if senior:
                senior_count += 1
            else:
                kept.append(p)
        relevant = kept

    added, dupes, auto_abandoned = upsert_found(relevant)

    print(
        f"Found {len(postings)} postings, {len(relevant)} relevant"
        + (f" ({senior_count} senior/experienced-required excluded)" if exclude_senior else "")
        + f", added {added} new to applied_log.csv ({dupes} already tracked, "
        + f"{auto_abandoned} auto-abandoned as non-US)."
    )


def _maybe_offer_cover_letter(profile, entry, config: dict) -> None:
    """Checks data/cover_letters/<slug>.{txt,pdf,docx} for this posting and,
    if found, points profile.resume.cover_letter_path at it for this fill
    only. If not found and the feature is enabled (search_config.yaml's
    cover_letters.enabled), pauses and tells you to ask Claude Code in chat
    to draft one -- deliberately not an API call from this script, so
    there's no extra cost or key to set up, at the cost of it being a
    manual step rather than a fully scripted one. Set enabled: false to
    never see this prompt.
    """
    profile.raw.setdefault("resume", {})["cover_letter_path"] = ""

    cl_config = config.get("cover_letters", {})
    if not cl_config.get("enabled", True):
        return

    save_dir = REPO_ROOT / cl_config.get("save_dir", "data/cover_letters")
    slug = slugify(entry.company, entry.role)

    def _find() -> pathlib.Path | None:
        for ext in (".txt", ".pdf", ".docx"):
            candidate = save_dir / f"{slug}{ext}"
            if candidate.exists():
                return candidate
        return None

    found = _find()
    if found:
        profile.raw["resume"]["cover_letter_path"] = str(found)
        print(f"Found a cover letter for this one ({found.name}) -- will attach it if the form has that field.")
        return

    print(
        f"\nNo cover letter saved yet for {entry.company} -- {entry.role}. "
        f"Want one? Ask me (Claude Code, in chat) to draft it for this posting "
        f"({entry.url}), save it to {save_dir}/{slug}.txt, then come back here."
    )
    input("Press Enter to continue (with one saved, or without to skip it for this posting)...")
    found = _find()
    if found:
        profile.raw["resume"]["cover_letter_path"] = str(found)
        print(f"Found {found.name} -- attaching.")


def cmd_review(args: argparse.Namespace) -> None:
    try:
        profile = load_profile()
    except ProfileError as e:
        print(str(e))
        sys.exit(1)

    try:
        config = load_search_config(args.config)
    except SearchConfigError as e:
        print(str(e))
        sys.exit(1)

    categories = [c.strip() for c in args.category.split(",")] if args.category else None
    interleave = not args.no_interleave
    full_queue = preview_queue(sort=args.sort, categories=categories, interleave=interleave)
    if not full_queue:
        print("Nothing to review -- run `python -m autofill search` first.")
        return

    preview = full_queue[: args.limit] if args.limit else full_queue
    print(
        f"\nShowing {len(preview)} of {len(full_queue)} found postings "
        f"({args.sort}{', interleaved by company' if interleave else ''}"
        + (f", categories={','.join(categories)}" if categories else "")
        + "):\n"
    )
    for i, e in enumerate(preview):
        tag = "fillable" if e.source in SUPPORTED_FILL_SOURCES else "manual apply -- no fill adapter"
        role = e.role if len(e.role) <= 55 else e.role[:52] + "..."
        print(f"[{i:3}] {e.company:15.15} {e.category:9.9} {role:55}  {tag}")

    choice = input(
        "\nEnter = review these in order  |  \"0,3,5\" = just those, in that order  |  q = cancel\n> "
    ).strip()
    if choice.lower() in ("q", "quit"):
        print("Cancelled.")
        return
    if choice:
        try:
            picked_indices = [int(x.strip()) for x in choice.split(",") if x.strip()]
            selected = [preview[i] for i in picked_indices]
        except (ValueError, IndexError):
            print("Couldn't parse that -- rerun `review` and try again.")
            return
    else:
        selected = preview

    manual_only = [e for e in selected if e.source not in SUPPORTED_FILL_SOURCES]
    if manual_only:
        print(f"\n{len(manual_only)} of those need manual apply (no fill adapter) -- skipping in this batch:")
        for e in manual_only:
            print(f"  {e.company} -- {e.role}: {e.url}")

    queue = [e for e in selected if e.source in SUPPORTED_FILL_SOURCES]
    if not queue:
        print("\nNothing fillable in that selection.")
    else:
        context, pw = open_persistent_context(headless=False)
        try:
            for entry in queue:
                print(f"\n=== {entry.company} -- {entry.role} ===")
                if entry.blurb:
                    print(entry.blurb)
                print(f"URL: {entry.url}")

                _maybe_offer_cover_letter(profile, entry, config)

                page = context.new_page()
                page.goto(entry.url)
                page.wait_for_load_state("domcontentloaded")

                filler = get_filler_for_url(entry.url)
                result = filler(page, profile)
                print(result.report())

                update_status(entry.url, "filled_pending_review", unmatched_fields="; ".join(result.skipped))

                answer = input(
                    "\nReview in the browser and submit yourself if it looks good, then:\n"
                    "  Enter  -- keep as filled_pending_review, move to the next one\n"
                    "  s      -- not doing this one right now, reset it back to 'found' for later, move to the next one\n"
                    "  a      -- not interested, mark it 'abandoned' (won't show up in review again)\n"
                    "  Ctrl+C -- stop the batch here (safe -- nothing is lost, this one stays filled_pending_review)\n"
                    "> "
                )
                choice = answer.strip().lower()
                if choice in ("s", "skip"):
                    update_status(entry.url, "found")
                    print(f"Reset {entry.company} -- {entry.role} back to 'found'.")
                elif choice in ("a", "abandon"):
                    update_status(entry.url, "abandoned")
                    print(f"Marked {entry.company} -- {entry.role} 'abandoned'.")
                try:
                    page.close()
                except Exception:
                    pass  # already closed manually -- fine, nothing to clean up
        finally:
            context.close()
            pw.stop()

        print("\nDone reviewing this batch. Re-run `review` any time -- it only "
              "picks up rows still marked 'found'/'queued'.")

    manual = needs_manual_apply()
    if manual:
        print(
            f"\n{len(manual)} Amazon/Google/TikTok posting(s) still need manual review "
            f"-- auto-fill isn't built for those yet."
        )


def cmd_dashboard(args: argparse.Namespace) -> None:
    if args.static:
        path = generate_and_open()
        print(f"Dashboard written to {path} and opened in your browser.")
        return
    run_dashboard_server(port=args.port)


def cmd_status(args: argparse.Namespace) -> None:
    entries = load_log()
    if not entries:
        print("applied_log.csv is empty -- run `search` first.")
        return

    if args.reset:
        # "filled_pending_review"/"pending" only mean "the tool touched this,
        # awaiting your confirmation" -- not a real-world outcome, so these
        # are always safe to bulk-reset back to "found". Never touches
        # applied/interview/rejected/offer, since those represent something
        # that actually happened and shouldn't be silently wiped.
        reset_count = 0
        for e in entries:
            if e.status in ("filled_pending_review", "pending"):
                update_status(e.url, "found")
                print(f"{e.company} -- {e.role}: {e.status} -> found")
                reset_count += 1
        print(f"\n{reset_count} entr{'y' if reset_count == 1 else 'ies'} reset to 'found'.")
        return

    if args.list or args.index is None:
        for i, e in enumerate(entries):
            print(f"[{i:3}] {e.status:22} {e.company} -- {e.role}")
        if args.index is None:
            print(f"\nValid statuses: {', '.join(STATUSES)}")
            print("Update one with: python -m autofill status <index> <new-status>")
        return

    if not (0 <= args.index < len(entries)):
        print(f"No entry at index {args.index} -- run `status --list` to see valid indexes.")
        sys.exit(1)

    if args.new_status not in STATUSES:
        print(f"'{args.new_status}' isn't one of the known statuses: {', '.join(STATUSES)}")
        print("Using it anyway -- your call, but the dashboard's status breakdown won't recognize it.")

    entry = entries[args.index]
    update_status(entry.url, args.new_status)
    print(f"Updated [{args.index}] {entry.company} -- {entry.role}: {entry.status} -> {args.new_status}")


def cmd_mail(args: argparse.Namespace) -> None:
    try:
        creds = authenticate()
    except MailwatchError as e:
        print(str(e))
        sys.exit(1)

    messages = fetch_recent_messages(creds, query=args.query, max_results=args.max_results)
    if not messages:
        print(f"No messages matching '{args.query}'.")
        return

    for m in messages:
        print(f"\nFrom:    {m['from']}")
        print(f"Subject: {m['subject']}")
        print(f"Date:    {m['date']}")
        print(f"Snippet: {m['snippet']}")


# Only move a status forward, never backward -- so an unrelated later email
# that happens to match a company can't accidentally downgrade e.g.
# "interview" back to "applied". rejected/offer/abandoned rank equally as
# terminal -- once you've deliberately marked something abandoned, neither
# mail-check nor a re-run of `fill` will move it to anything else.
_STATUS_RANK = {
    "found": 0, "queued": 0, "pending": 0,
    "filled_pending_review": 1,
    "applied": 2,
    "interview": 3,
    "rejected": 4, "offer": 4, "abandoned": 4,
}


def cmd_mail_check(args: argparse.Namespace) -> None:
    try:
        creds = authenticate()
    except MailwatchError as e:
        print(str(e))
        sys.exit(1)

    messages = fetch_recent_messages(creds, query=args.query, max_results=args.max_results)
    entries = load_log()
    if not entries:
        print("applied_log.csv is empty -- nothing to match mail against.")
        return

    seen_ambiguous = load_seen_ambiguous()
    updated = 0
    ambiguous = []
    already_seen_count = 0
    for m in messages:
        if is_non_application_email(m["subject"], m["snippet"]):
            continue  # account/portal mechanics (verification codes, security alerts) -- not a status signal

        entry = match_company(m, entries)
        if entry is None:
            continue  # doesn't match any tracked company -- ignored (this is the spam/newsletter filter)

        new_status = classify_email(m["subject"], m["snippet"])
        if new_status is None:
            if m["id"] in seen_ambiguous:
                already_seen_count += 1
                continue
            ambiguous.append((entry, m))
            continue

        if _STATUS_RANK.get(new_status, 0) < _STATUS_RANK.get(entry.status, 0) or new_status == entry.status:
            continue  # already at or past this status -- don't regress or no-op update

        old_status = entry.status
        update_status(entry.url, new_status)
        entry.status = new_status  # keep the in-memory copy current -- otherwise a second
        # email matching this same entry later in this run still sees the stale status and
        # prints a redundant "transition" for a change that already happened moments ago
        print(f"{entry.company} -- {entry.role}: {old_status} -> {new_status}  (\"{m['subject']}\")")
        updated += 1

    if ambiguous:
        print(f"\n{len(ambiguous)} new email(s) matched a tracked company but weren't clearly classifiable -- read these yourself (won't be shown again after this):")
        for entry, m in ambiguous:
            print(f"  {entry.company} -- {entry.role}: \"{m['subject']}\" -- {m['snippet'][:120]}")
        seen_ambiguous.update(m["id"] for _, m in ambiguous)
        save_seen_ambiguous(seen_ambiguous)
    if already_seen_count:
        print(f"\n({already_seen_count} previously-shown ambiguous email(s) suppressed -- already read once.)")

    print(f"\n{updated} status update(s) made.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="autofill")
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="Open a browser to log into a site once (session persists)")
    p_login.add_argument("url", nargs="?", default=None)
    p_login.set_defaults(func=cmd_login)

    p_fill = sub.add_parser("fill", help="Navigate to a job application URL, fill the form, and track it")
    p_fill.add_argument("url")
    p_fill.add_argument("--company", default=None, help="Override the guessed company name in applied_log.csv")
    p_fill.add_argument("--role", default=None, help="Override the guessed role/title in applied_log.csv")
    p_fill.add_argument("--no-track", action="store_true", help="Don't add this to applied_log.csv, just fill it")
    p_fill.set_defaults(func=cmd_fill)

    p_search = sub.add_parser("search", help="Find new postings and add relevant ones to applied_log.csv")
    p_search.add_argument("--config", default=None, help="Path to search_config.yaml (default: data/search_config.yaml)")
    p_search.add_argument(
        "--no-browser-search",
        action="store_true",
        help="Skip LinkedIn/Amazon/Google/TikTok (browser-based); Greenhouse/Lever only",
    )
    p_search.set_defaults(func=cmd_search)

    p_review = sub.add_parser("review", help="Fill queued postings one at a time, review/submit each yourself")
    p_review.add_argument("--config", default=None, help="Path to search_config.yaml (default: data/search_config.yaml)")
    p_review.add_argument("--sort", choices=["newest", "oldest"], default="newest", help="Order by found date (default: newest first)")
    p_review.add_argument("--category", default=None, help="Only these categories, comma-separated (e.g. IT,SRE,SDE,Security,Data)")
    p_review.add_argument("--limit", type=int, default=15, help="How many postings to show in the pre-flight list (default: 15; 0 = show all)")
    p_review.add_argument("--no-interleave", action="store_true", help="Use a flat sort instead of round-robin-by-company (the flat sort is what let one company's backlog dominate the queue)")
    p_review.set_defaults(func=cmd_review)

    p_dashboard = sub.add_parser("dashboard", help="Live, editable dashboard (or a one-shot static file with --static)")
    p_dashboard.add_argument("--static", action="store_true", help="Write a static dashboard.html instead of running the live server")
    p_dashboard.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port for the live server (default: {DEFAULT_PORT})")
    p_dashboard.set_defaults(func=cmd_dashboard)

    p_status = sub.add_parser("status", help="List tracked postings or manually correct one's status")
    p_status.add_argument("index", nargs="?", type=int, default=None, help="Row index from `status --list`")
    p_status.add_argument("new_status", nargs="?", default=None, help="New status value")
    p_status.add_argument("--list", action="store_true", help="List all tracked postings with their index")
    p_status.add_argument(
        "--reset",
        action="store_true",
        help="Bulk-reset every 'filled_pending_review'/'pending' entry back to 'found' (never touches applied/interview/rejected/offer)",
    )
    p_status.set_defaults(func=cmd_status)

    p_mail = sub.add_parser("mail", help="List recent Gmail messages (read-only)")
    p_mail.add_argument("--query", default="newer_than:3d", help="Gmail search query (default: newer_than:3d)")
    p_mail.add_argument("--max-results", type=int, default=30, dest="max_results")
    p_mail.set_defaults(func=cmd_mail)

    p_mail_check = sub.add_parser("mail-check", help="Match recent mail to tracked applications and update statuses")
    p_mail_check.add_argument("--query", default="newer_than:2d", help="Gmail search query (default: newer_than:2d)")
    p_mail_check.add_argument("--max-results", type=int, default=50, dest="max_results")
    p_mail_check.set_defaults(func=cmd_mail_check)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
