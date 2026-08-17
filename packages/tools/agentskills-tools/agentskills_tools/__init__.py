"""Command line tools for authoring and validating Agent Skills.

The console script is ``agentskills``.  Every command is also reachable
in-process through :func:`~agentskills_tools.cli.main`, which takes an
argument list and returns an exit code rather than calling
:func:`sys.exit` — that is what makes it testable.
"""

from agentskills_tools.cli import main
from agentskills_tools.discovery import CliError, SkillLocation, discover
from agentskills_tools.findings import Finding, SkillReport

__all__ = [
    "CliError",
    "Finding",
    "SkillLocation",
    "SkillReport",
    "discover",
    "main",
]
