# v0.1.0 Release Notes (English)

Release date: 2026-03-21  
Tag: `v0.1.0`

## Release Scope

`v0.1.0` is the first public baseline release of this project.  
It establishes a reproducible, deployable, and collaboration-ready foundation for an A-share / ETF trading assistant on OpenClaw.

The default product narrative is stocks and ETFs. Options-related capabilities are kept as optional extensions.

## Highlights

- Established the OpenClaw integration baseline: multi-agent collaboration, workflow scheduling, tool registration, and runtime execution path.
- Delivered the core operational loop: data collection, analysis, risk checks, notifications, and traceable runtime artifacts.
- Added open-source release essentials: `README`, `LICENSE`, `SECURITY`, `CONTRIBUTING`, `CHANGELOG`, and `.env.example`.
- Introduced release safety gates: JSON syntax checks, release safety scan, and CI workflow (`release-gate`).
- Refactored documentation structure: execution-oriented docs in `docs/publish/*`, historical materials moved to `docs/archive/*` and `docs/legacy/*`.

## Intended Audience

- Users building A-share / ETF workflow automation on OpenClaw.
- Developers and operators who need an extensible baseline for a trading-assistant system.

## Notes

- This repository is for research and engineering practice only, not investment advice.
- The repository name `etf-options-ai-assistant` is kept for compatibility and does not define the current product focus.

## Next Milestones

- `v0.2.x`: stronger strategy modularization, expanded intraday risk templates, and further docs consolidation.
- `v1.0.0`: standardized production deployment, rollback, and operational inspection workflows.
