"""LinkedIn Easy Apply flow.

Easy Apply is a multi-step modal (Next -> Next -> ... -> Review -> Submit).
This clicks "Easy Apply", fills each step with the generic label matcher
scoped to the modal, and advances via Next/Review -- but it STOPS at the
final review step and will never click "Submit application" for you.
Review the summary in the browser window and submit yourself.
"""

from __future__ import annotations

from playwright.sync_api import Page

from ..profile import Profile
from .generic import FillResult, fill_generic_form

MODAL_SELECTOR = "div.jobs-easy-apply-modal, div[role='dialog']"


def run_easy_apply(page: Page, profile: Profile, max_steps: int = 10) -> FillResult:
    total = FillResult()

    easy_apply_btn = page.locator("button:has-text('Easy Apply')").first
    if easy_apply_btn.count() == 0:
        print("No 'Easy Apply' button found -- is this a LinkedIn job posting URL, and are you logged in?")
        print("Tip: run `python -m autofill login` first to log into LinkedIn.")
        return total

    easy_apply_btn.click()
    page.wait_for_timeout(1000)

    for step in range(max_steps):
        modal = page.locator(MODAL_SELECTOR).first
        if modal.count() == 0:
            print("Easy Apply modal not found -- stopping so you can finish manually.")
            return total

        result = fill_generic_form(page, profile, scope=modal)
        total.filled += result.filled
        total.skipped += result.skipped
        print(f"--- Easy Apply step {step + 1} ---")
        print(result.report())

        submit_btn = modal.locator("button:has-text('Submit application')")
        if submit_btn.count() > 0:
            print(
                "\nReached the final review step. This tool will NOT click "
                "'Submit application' for you -- review everything in the "
                "browser window, then click Submit yourself."
            )
            return total

        next_btn = modal.locator("button:has-text('Next'), button:has-text('Review')")
        if next_btn.count() == 0:
            print("No Next/Review button found -- stopping so you can finish manually.")
            return total

        next_btn.first.click()
        page.wait_for_timeout(1200)

    print("Hit max_steps without reaching the review screen -- finish this one manually.")
    return total
