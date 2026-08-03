"""Command line tools for authoring and validating Agent Skills.

The console script is ``agentskills``.  Every command is also reachable
in-process through :func:`~agentskills_cli.cli.main`, which takes an
argument list and returns an exit code rather than calling
:func:`sys.exit` — that is what makes it testable.
"""

from agentskills_cli.cli import main
from agentskills_cli.discovery import CliError, SkillLocation, discover
from agentskills_cli.findings import Finding, SkillReport

__all__ = [
    "CliError",
    "Finding",
    "SkillLocation",
    "SkillReport",
    "discover",
    "main",
]
