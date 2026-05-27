"""Direct Python entry for Claude Code's Stop hook.

Invoked by Claude Code without a shell wrapper so stdin reaches Python
with its original byte encoding from Claude Code (a PowerShell or bash
middleman re-encodes the bytes and corrupts the JSON payload).

If `LISTEN_CLAUDE_URL` is set in the environment, the payload is
forwarded to that URL (typically an SSH-tunnelled local listener on
the user's workstation) instead of being synthesised and played here.
That's the path used when Claude Code runs inside an SSH session / on
a remote dev box — the audio still comes out of the user's actual
speakers.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from listen_bridge import forward
from listen_bridge.runner import process_stop

sys.exit(forward.forward_or_local("Stop", process_stop))
