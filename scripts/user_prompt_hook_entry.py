"""UserPromptSubmit hook entry.

Captures the first non-empty line of each user prompt as that
session's "current activity" title — used by the Notification hook
to announce which window is asking by what it's doing, not just by
project directory.

Same local-vs-remote split as the Stop / Notification entries: if
LISTEN_CLAUDE_URL is set, forward to the workstation listener.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from listen_bridge import forward, llm
from listen_bridge.runner import process_user_prompt


def main() -> int:
    # Skip the inner `claude -p` summarisation calls — they fire a
    # UserPromptSubmit hook for the rewrite-wrapper prompt, which would
    # otherwise pollute the user's actual session title with our own
    # internal instructions. Filter here (before deciding whether to
    # forward) so the remote → local hop also stays clean.
    if llm.is_inner_summarization_call():
        return 0
    return forward.forward_or_local("UserPromptSubmit", process_user_prompt)


if __name__ == "__main__":
    sys.exit(main())
