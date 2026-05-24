"""Entry-point shim: runs the listen_bridge.voice_clone CLI under the
main Listen-Claude venv (because that's where yt-dlp lives). Each
sub-command may shell out to .venv-gptsovits when it needs GPT-SoVITS
internals (transcribe, train)."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repo root is on sys.path so the relative-import of
# listen_bridge resolves regardless of how the script is launched.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from listen_bridge.voice_clone.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
