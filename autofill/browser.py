"""Launches a persistent, visible Chromium context.

Using a persistent user-data-dir means that once you log into LinkedIn /
Workday / etc. one time through this tool, the session cookie is saved on
disk (in browser_profile/) and future runs stay logged in -- same as a
normal Chrome profile. Headless is off by default on purpose: you should
be watching while it fills forms, both to catch mistakes and because most
of these sites actively try to detect and block headless/bot traffic.
"""

from __future__ import annotations

import pathlib

from playwright.sync_api import BrowserContext, sync_playwright

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROFILE_DIR = REPO_ROOT / "browser_profile"


def open_persistent_context(headless: bool = False) -> tuple[BrowserContext, "PlaywrightCtx"]:
    """Returns (context, playwright_handle). Caller is responsible for closing both.

    Usage:
        context, pw = open_persistent_context()
        page = context.new_page()
        ...
        context.close()
        pw.stop()
    """
    PROFILE_DIR.mkdir(exist_ok=True)
    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        viewport={"width": 1400, "height": 900},
        args=["--start-maximized"] if not headless else [],
    )
    return context, pw
