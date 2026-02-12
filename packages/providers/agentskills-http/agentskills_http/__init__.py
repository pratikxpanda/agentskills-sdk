"""HTTP-based skill providers for the Agent Skills format.

This package provides :class:`HTTPStaticFileSkillProvider`, a concrete
implementation of :class:`~agentskills_core.SkillProvider` that fetches
`Agent Skills <https://agentskills.io>`_ from a static HTTP file host
(S3, Azure Blob Storage, CDN, GitHub Pages, or any web server serving
raw files).

Install::

    pip install agentskills-http
"""

from agentskills_http.static import HTTPStaticFileSkillProvider

__all__ = ["HTTPStaticFileSkillProvider"]
