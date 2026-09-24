"""Read-only Gmail access for tracking job-application replies.

Uses raw Gmail REST calls via `requests` (already a dependency) rather than
the full google-api-python-client library, to avoid pulling in its heavy
transitive dependency chain for what's just a handful of GET requests.

First run opens a browser for you to approve read-only access once
(gmail.readonly scope -- this can never send, delete, or modify anything).
The resulting token is cached to data/gmail_token.json (gitignored) and
auto-refreshed after that, so scheduled/unattended runs don't need you
present again unless the refresh token itself is revoked.
"""

from __future__ import annotations

import pathlib
from typing import Any

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CLIENT_SECRET_PATH = REPO_ROOT / "data" / "google_client_secret.json"
TOKEN_PATH = REPO_ROOT / "data" / "gmail_token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class MailwatchError(RuntimeError):
    pass


def authenticate() -> Credentials:
    """Returns valid Credentials, refreshing the cached token if possible,
    or running the one-time interactive consent flow (opens a browser) if
    there's no cached token yet or it can't be refreshed.
    """
    creds: Credentials | None = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())
        return creds

    if not CLIENT_SECRET_PATH.exists():
        raise MailwatchError(
            f"No {CLIENT_SECRET_PATH} found -- see README for the Google Cloud "
            f"Console setup steps (OAuth client, Desktop app type)."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json())
    return creds


def _decode_header(headers: list[dict[str, str]], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def fetch_recent_messages(creds: Credentials, query: str = "newer_than:3d", max_results: int = 30) -> list[dict[str, Any]]:
    """Returns [{id, from, subject, date, snippet}, ...] for messages
    matching `query` (Gmail search syntax, e.g. "newer_than:3d",
    "is:unread"). Read-only -- never marks anything read, moves, or
    deletes.
    """
    headers = {"Authorization": f"Bearer {creds.token}"}

    resp = requests.get(
        f"{API_BASE}/messages",
        headers=headers,
        params={"q": query, "maxResults": max_results},
        timeout=15,
    )
    resp.raise_for_status()
    ids = [m["id"] for m in resp.json().get("messages", [])]

    messages = []
    for msg_id in ids:
        detail_resp = requests.get(
            f"{API_BASE}/messages/{msg_id}",
            headers=headers,
            params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
            timeout=15,
        )
        detail_resp.raise_for_status()
        detail = detail_resp.json()
        payload_headers = detail.get("payload", {}).get("headers", [])
        messages.append(
            {
                "id": msg_id,
                "from": _decode_header(payload_headers, "From"),
                "subject": _decode_header(payload_headers, "Subject"),
                "date": _decode_header(payload_headers, "Date"),
                "snippet": detail.get("snippet", ""),
            }
        )
    return messages
