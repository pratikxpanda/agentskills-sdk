"""Entry point for ``python -m agentskills_cli`` and the ``agentskills`` script."""

from __future__ import annotations

import sys

from agentskills_cli.cli import main

if __name__ == "__main__":
    sys.exit(main())
