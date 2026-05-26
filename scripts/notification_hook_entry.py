"""Direct Python entry for Claude Code's Notification hook.

Mirror of stop_hook_entry.py — invoked by Claude Code without a shell
wrapper so stdin reaches Python with its original byte encoding (a
PowerShell or bash middleman would re-encode the bytes and corrupt
non-ASCII JSON in the payload).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from listen_bridge.runner import notification_main

sys.exit(notification_main())
