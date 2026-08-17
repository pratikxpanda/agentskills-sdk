"""Entry point for ``python -m agentskills_tools`` and the ``agentskills`` script."""

from __future__ import annotations

import sys

from agentskills_tools.cli import main

if __name__ == "__main__":
    sys.exit(main())
