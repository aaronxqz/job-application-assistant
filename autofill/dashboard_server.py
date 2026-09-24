"""Small local HTTP server (127.0.0.1 only, never exposed beyond your own
machine) that serves a live, editable dashboard -- each row's status is a
real dropdown; picking one writes to applied_log.csv immediately via
tracking.update_status(), then the page reloads to show the update.
"""

from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from .dashboard import build_stats, render_html
from .tracking import STATUSES, load_log, update_status

DEFAULT_PORT = 8765


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        pass  # this runs in the foreground -- keep the terminal quiet

    def do_GET(self) -> None:
        if self.path.split("?")[0] not in ("/", ""):
            self.send_response(404)
            self.end_headers()
            return
        entries = load_log()
        stats = build_stats(entries)
        html = render_html(stats, entries, interactive=True)
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/update-status":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
            url, status = data["url"], data["status"]
            if status not in STATUSES:
                raise ValueError(f"unknown status: {status!r}")
            update_status(url, status)
        except Exception as e:
            body = str(e).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.end_headers()


def run(port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    server = HTTPServer(("127.0.0.1", port), _Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Dashboard running at {url} (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
