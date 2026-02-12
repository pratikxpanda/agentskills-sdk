"""Local filesystem-based skill provider for the Agent Skills format.

This package provides :class:`LocalFileSystemSkillProvider`, a concrete
implementation of :class:`~agentskills_core.SkillProvider` that reads
`Agent Skills <https://agentskills.io>`_ from a local directory tree.

Install::

    pip install agentskills-fs
"""

from agentskills_fs.local import LocalFileSystemSkillProvider

__all__ = ["LocalFileSystemSkillProvider"]
