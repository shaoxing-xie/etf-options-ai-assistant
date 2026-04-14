# Contributing Guide

Thanks for contributing.

Repository naming note: this repository keeps the name `etf-options-ai-assistant` for compatibility with existing scripts and deployment paths. Current product positioning is A-share/ETF first, with options as optional extensions.

## Branch Naming

Use short, descriptive branch names:

- `feat/<topic>`
- `fix/<topic>`
- `docs/<topic>`
- `chore/<topic>`

Example: `feat/model-route-fallbacks`

## Commit Message Style

Recommended format:

- `feat: ...`
- `fix: ...`
- `docs: ...`
- `chore: ...`
- `refactor: ...`
- `test: ...`

Keep messages focused on why the change is needed.

## Pull Request Checklist

- [ ] Code compiles/runs locally
- [ ] No real secrets or credentials are committed
- [ ] Docs updated if behavior changed
- [ ] Config files remain environment-driven (no hardcoded local paths)
- [ ] Basic checks pass
- [ ] **若改动 `plugins/notification/**`**（钉钉长文、日报版式、`tool_send_daily_report` 等）：在 **PR 描述或首条评论** 中显式写一行 `AUTOFIX_ALLOWED=false`（与 `config/evolver_scope.yaml` 的 `denied_paths` 及 `docs/research/daily_market_report_web_benchmark.md` §3 一致，防止自动演化/误合并）。

打开 PR 时仓库会提供 `.github/pull_request_template.md` 中的同款提醒。

## Local Validation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

- 集成/长耗时脚本（数据管线、工作流串跑、合并工具冒烟）见 `tests/README.md`，按需手动执行，不必在每次 PR 全跑。
- 运维与发布辅助脚本说明见 `scripts/README.md`.

If OpenClaw integration is touched, include a brief test note in PR description.
