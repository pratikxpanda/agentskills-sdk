"""Compile package examples and run selected local quick starts without network access."""

from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
from pathlib import Path

from check_release_version import PACKAGES, ROOT
from markdown_it import MarkdownIt


def _blocks(document: Path, language: str) -> list[str]:
    return [
        token.content
        for token in MarkdownIt().parse(document.read_text(encoding="utf-8"))
        if token.type == "fence" and token.info.strip() == language
    ]


def _quick_start(document: Path) -> str:
    for code in _blocks(document, "python"):
        tree = ast.parse(code)
        for node in tree.body:
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and isinstance(node.value.func.value, ast.Name)
                and node.value.func.value.id == "asyncio"
                and node.value.func.attr == "run"
            ):
                return code
    raise ValueError(f"Runnable asyncio quick start missing: {document}")


def _execute(code: str, work: Path, label: str, *, without_mcp: bool = False) -> None:
    if without_mcp:
        code = "import sys; sys.modules['mcp'] = None\n" + code
    subprocess.run([sys.executable, "-c", code], cwd=work, check=True, timeout=60)
    print(f"PASS {label}", flush=True)


def main() -> int:
    """Validate README example syntax and selected local application/test workflows."""
    packages = {Path(path).name: ROOT / path / "README.md" for path in PACKAGES}
    documents = [ROOT / "README.md", *packages.values()]
    count = 0
    try:
        for document in documents:
            for index, code in enumerate(_blocks(document, "python")):
                compile(
                    code,
                    f"{document} example {index}",
                    "exec",
                    flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
                )
                count += 1
        with tempfile.TemporaryDirectory(prefix="agentskills-docs-") as temporary:
            work = Path(temporary)
            sample = _blocks(ROOT / "README.md", "markdown")[0]
            for directory in ("skills", "my-skills"):
                skill = work / directory / "incident-response"
                skill.mkdir(parents=True)
                (skill / "SKILL.md").write_text(sample, encoding="utf-8")
            (work / "AGENTS.md").write_text(
                "# Team instructions\nRun the test suite.\n", encoding="utf-8"
            )
            _execute(_quick_start(ROOT / "README.md"), work, "root README", without_mcp=True)
            for name in (
                "agentskills-core",
                "agentskills-fs",
                "agentskills-adapters",
                "agentskills-retrieval",
                "agentskills-testing",
            ):
                _execute(_quick_start(packages[name]), work, name)
            tests = _blocks(packages["agentskills-testing"], "python")
            test_file = work / "test_readme_examples.py"
            test_file.write_text("\n".join([tests[0], tests[1], tests[-1]]), encoding="utf-8")
            subprocess.run(
                [sys.executable, "-m", "pytest", str(test_file), "-q", "--no-header"],
                cwd=work,
                check=True,
                timeout=60,
            )
        print(f"Validated {count} Python snippets and selected local quick starts.")
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError) as exc:
        print(f"Documentation example check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
