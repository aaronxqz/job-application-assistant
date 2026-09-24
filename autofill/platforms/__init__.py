from __future__ import annotations

from urllib.parse import urlparse

from playwright.sync_api import Page

from ..profile import Profile
from .generic import FillResult, fill_generic_form
from .linkedin import run_easy_apply


def get_filler_for_url(url: str):
    """Pick a filler function based on the URL's domain.

    Returns a callable: filler(page, profile) -> FillResult
    """
    host = urlparse(url).netloc.lower()

    def linkedin_filler(page: Page, profile: Profile) -> FillResult:
        return run_easy_apply(page, profile)

    def generic_filler(page: Page, profile: Profile) -> FillResult:
        # Covers Greenhouse, Lever, and most plain company career-page forms.
        # Workday is intentionally NOT special-cased -- see README/NOTES.md,
        # its custom dropdown widgets need per-field handling this generic
        # matcher can't do reliably. It'll still fill plain text fields.
        return fill_generic_form(page, profile)

    if "linkedin.com" in host:
        return linkedin_filler
    return generic_filler
