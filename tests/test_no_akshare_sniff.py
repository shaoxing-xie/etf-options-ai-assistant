"""
Fail if direct akshare imports appear under skills/ (skills must use plugin tools, not ad-hoc akshare).

Note: `src/` may still contain legacy collectors; gate skills/workflows first.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = [ROOT / "skills"]
FORBIDDEN = ("akshare", "AkShare")


def _imports_in_file(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0].lower() == "akshare":
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".", 1)[0].lower() == "akshare":
                found.append(node.module)
    return found


def test_no_akshare_imports_in_skills_and_src():
    hits: list[tuple[str, str]] = []
    for base in SCAN_DIRS:
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if "venv" in path.parts or ".git" in path.parts:
                continue
            for mod in _imports_in_file(path):
                hits.append((str(path.relative_to(ROOT)), mod))
    assert not hits, f"Direct akshare imports disallowed: {hits}"
