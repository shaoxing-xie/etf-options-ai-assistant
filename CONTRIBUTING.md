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

## Local Validation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q || true
```

If OpenClaw integration is touched, include a brief test note in PR description.
