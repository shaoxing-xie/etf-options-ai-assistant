#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml


KEY_FIELD_PATTERN = re.compile(r"(api[_-]?key|token|secret|password)", re.IGNORECASE)


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _resolve_placeholder(val: str) -> tuple[bool, str]:
    s = str(val or "").strip()
    if not s:
        return False, "empty"
    if s.startswith("${") and s.endswith("}") and len(s) > 3:
        env_name = s[2:-1].strip()
        env_val = os.getenv(env_name, "").strip()
        if env_val:
            return True, f"resolved:{env_name} (len={len(env_val)})"
        return False, f"missing_env:{env_name}"
    return True, "literal"


def _scan(node: Any, path: str, findings: list[tuple[str, bool, str]]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}" if path else str(k)
            if KEY_FIELD_PATTERN.search(str(k)):
                if isinstance(v, list):
                    ok_all = True
                    msgs = []
                    for idx, item in enumerate(v):
                        ok, msg = _resolve_placeholder(str(item))
                        ok_all = ok_all and ok
                        msgs.append(f"{idx}:{msg}")
                    findings.append((p, ok_all, "; ".join(msgs)))
                else:
                    ok, msg = _resolve_placeholder(str(v))
                    findings.append((p, ok, msg))
            _scan(v, p, findings)
    elif isinstance(node, list):
        for i, x in enumerate(node):
            _scan(x, f"{path}[{i}]", findings)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    _load_env_file(Path.home() / ".openclaw" / ".env")
    _load_env_file(root / ".env")

    cfg_path = root / "config" / "domains" / "market_data.yaml"
    if not cfg_path.is_file():
        print(f"missing config: {cfg_path}")
        return 1
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    findings: list[tuple[str, bool, str]] = []
    _scan(cfg, "", findings)

    ok_count = sum(1 for _, ok, _ in findings if ok)
    bad = [(p, msg) for p, ok, msg in findings if not ok]
    print(f"key_fields_total={len(findings)} ok={ok_count} bad={len(bad)}")
    for p, ok, msg in findings:
        status = "OK " if ok else "BAD"
        print(f"[{status}] {p}: {msg}")
    if bad:
        print("\n-- Missing/invalid key hints --")
        for p, msg in bad:
            print(f"- {p}: {msg}")
    return 0 if not bad else 2


if __name__ == "__main__":
    raise SystemExit(main())

