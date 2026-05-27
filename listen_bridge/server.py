"""Local HTTP listener that receives Claude Code hook payloads from
remote Claude Code agents (over an SSH reverse tunnel) and processes
them locally — i.e. synthesises and plays audio on the workstation
where this server is running.

Usage on the workstation:
    python scripts/listen-claude-server.py
        --host 127.0.0.1 --port 7878

Then SSH into the remote with:
    ssh -R 7878:localhost:7878 user@remote

And in the remote .env:
    LISTEN_CLAUDE_URL=http://127.0.0.1:7878
    LISTEN_CLAUDE_TOKEN=<shared-secret>    (optional but recommended)

The remote's hook scripts will POST the raw stdin Claude Code gave
them straight back to this listener; this side handles all the
filtering, queueing, project alias lookup, and playback."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, runner


_EVENT_HANDLERS = {
    "Stop": runner.process_stop,
    "Notification": runner.process_notification,
    "UserPromptSubmit": runner.process_user_prompt,
}


class _Handler(BaseHTTPRequestHandler):
    server_version = "ListenClaude/1"

    def log_message(self, fmt, *args):  # noqa: N802 (override stdlib name)
        # Route stdlib's noisy access log into our own log file so the
        # console stays clean.
        try:
            runner._log(f"http {self.address_string()} - {fmt % args}")
        except Exception:
            pass

    def _send(self, code: int, body: bytes = b"", content_type: str = "text/plain") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _authorized(self) -> bool:
        if not config.LISTEN_CLAUDE_TOKEN:
            return True
        got = self.headers.get("Authorization", "")
        return got == f"Bearer {config.LISTEN_CLAUDE_TOKEN}"

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._send(200, b"ok\n")
            return
        self._send(404)

    def do_POST(self):  # noqa: N802
        if self.path != "/hook":
            self._send(404)
            return
        if not self._authorized():
            self._send(401, b"unauthorized\n")
            return

        event = self.headers.get("X-Hook-Event", "")
        handler = _EVENT_HANDLERS.get(event)
        if not handler:
            self._send(400, f"unknown event: {event}\n".encode("utf-8"))
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace") or "{}")
        except json.JSONDecodeError as e:
            self._send(400, f"bad json: {e}\n".encode("utf-8"))
            return

        # Run the handler in a daemon thread — the worker drain inside
        # process_stop / process_notification can take seconds, but we
        # want the HTTP client (the remote hook subprocess) to release
        # immediately so Claude Code's hook timeout doesn't fire.
        threading.Thread(
            target=_dispatch_safely, args=(handler, payload, event), daemon=True
        ).start()
        self._send(202, b"queued\n")


def _dispatch_safely(handler, payload, event):
    try:
        handler(payload)
    except Exception as e:
        runner._log(f"server {event} handler failed: {e}")


def serve(host: str, port: int) -> None:
    httpd = ThreadingHTTPServer((host, port), _Handler)
    runner._log(f"listen-claude-server listening on {host}:{port}")
    print(f"listen-claude-server listening on {host}:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        runner._log("listen-claude-server shutting down")
        httpd.server_close()
