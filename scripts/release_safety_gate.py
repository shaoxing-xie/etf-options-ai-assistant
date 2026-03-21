#!/usr/bin/env python3
"""
Release safety gate checks:
1) Absolute path leakage
2) Plaintext secret-like strings
3) Local-machine-only hardcoded config hints
"""

from __future__ import annotations

import pathlib
import re
import sys
from typing import Iterable


ROOT = pathlib.Path(__file__).resolve().parents[1]

INCLUDE_SUFFIXES = {
    ".py",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".txt",
    ".env",
    ".example",
    ".cfg",
    ".ts",
    ".js",
    ".sh",
}

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    ".venv_yf",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "node_modules",
    "docs/assets",
    "docs",
    "memory",
}

EXCLUDE_FILES = {
    ".env",
}

ALLOWED_TOP_PREFIXES = (
    "src/",
    "scripts/",
    "plugins/",
    "workflows/",
    "config/",
    ".github/workflows/",
)

ALLOWED_ROOT_FILES = {
    "README.md",
    "README.en.md",
    "config.yaml",
    "Prompt_config.yaml",
    ".env.example",
    ".gitignore",
    "LICENSE",
    "SECURITY.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
}

ABS_PATH_PATTERNS = [
    re.compile(r"/home/xie(?:/|$)"),
    re.compile(r"/home/ipentacle(?:/|$)"),
]

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|webhook)\s*[:=]\s*['\"][^'\"]{10,}['\"]"),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9_\-\.]{20,}"),
]

LOCAL_ONLY_PATTERNS = [
    re.compile(r"~/.openclaw"),
    re.compile(r"/tmp/openclaw"),
    re.compile(r"127\.0\.0\.1:18789"),
]

ALLOWLIST_SNIPPETS = {
    "OPENCLAW_GATEWAY_TOKEN",
    "ETF_TUSHARE_TOKEN",
    "OPENCLAW_OPENROUTER_API_KEY",
    "example",
    "placeholder",
}


def iter_files(root: pathlib.Path) -> Iterable[pathlib.Path]:
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(root).as_posix()
        if any(rel == d or rel.startswith(d + "/") for d in EXCLUDE_DIRS):
            continue
        if "/.mypy_cache/" in rel or "/.ruff_cache/" in rel or "/.pytest_cache/" in rel:
            continue
        if p.name in EXCLUDE_FILES:
            continue
        if rel not in ALLOWED_ROOT_FILES and not rel.startswith(ALLOWED_TOP_PREFIXES):
            continue
        if p.suffix in INCLUDE_SUFFIXES or p.name.endswith(".env.example"):
            yield p


def is_probably_allowed(line: str) -> bool:
    lower = line.lower()
    return any(x.lower() in lower for x in ALLOWLIST_SNIPPETS)


def scan_file(path: pathlib.Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:  # pragma: no cover
        errors.append(f"{path}: read error: {exc}")
        return errors, warnings

    rel = path.relative_to(ROOT).as_posix()
    suffix = path.suffix.lower()
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for pat in ABS_PATH_PATTERNS:
            if pat.search(line):
                if suffix == ".md":
                    warnings.append(f"{rel}:{i}: absolute path in markdown -> {stripped[:160]}")
                else:
                    errors.append(f"{rel}:{i}: absolute path leak -> {stripped[:160]}")
        for pat in SECRET_PATTERNS:
            if "${" in line:
                continue
            if "{" in line and "}" in line:
                # likely template/f-string placeholder rather than literal secret
                continue
            if pat.search(line) and not is_probably_allowed(line):
                if suffix == ".md":
                    warnings.append(f"{rel}:{i}: possible secret example in markdown -> {stripped[:160]}")
                else:
                    errors.append(f"{rel}:{i}: possible plaintext secret -> {stripped[:160]}")
        for pat in LOCAL_ONLY_PATTERNS:
            if pat.search(line):
                warnings.append(f"{rel}:{i}: local-only hardcoded hint -> {line.strip()[:160]}")
    return errors, warnings


def main() -> int:
    all_errors: list[str] = []
    all_warnings: list[str] = []
    for file_path in iter_files(ROOT):
        errors, warnings = scan_file(file_path)
        all_errors.extend(errors)
        all_warnings.extend(warnings)

    if all_warnings:
        print("Release safety gate warnings:")
        for warning in all_warnings:
            print(f"- {warning}")

    if all_errors:
        print("Release safety gate failed. Errors:")
        for issue in all_errors:
            print(f"- {issue}")
        return 1

    print("Release safety gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
