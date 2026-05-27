"""Run the Listen-Claude local HTTP listener.

Used when Claude Code is running on a *different* machine (a remote
dev box reached via SSH, an IDE-over-SSH session, etc.) — the user's
workstation runs this listener; the remote's hook scripts POST their
Claude Code payloads back through an SSH reverse tunnel so the audio
plays on the workstation where the user actually is.

Quick setup:

    # On the workstation (Mac / Windows):
    python scripts/listen-claude-server.py

    # In another terminal, SSH into the dev box:
    ssh -R 7878:localhost:7878 user@remote

    # On the remote, set in .env:
    LISTEN_CLAUDE_URL=http://127.0.0.1:7878
    LISTEN_CLAUDE_TOKEN=...   # optional shared secret

That's it — remote Claude Code's Stop/Notification/UserPromptSubmit
hooks will all transparently forward to the workstation.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from listen_bridge import config, server


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default=config.LISTEN_CLAUDE_SERVER_HOST)
    p.add_argument("--port", type=int, default=config.LISTEN_CLAUDE_SERVER_PORT)
    args = p.parse_args()
    server.serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
