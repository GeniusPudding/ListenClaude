"""Notification-hook entry point.

If LISTEN_CLAUDE_URL is set, the payload is forwarded to the
workstation listener over SSH tunnel; otherwise it's processed locally
exactly like before. See stop_hook_entry.py for the full rationale on
the local-vs-remote split.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from listen_bridge import forward
from listen_bridge.runner import process_notification

sys.exit(forward.forward_or_local("Notification", process_notification))
