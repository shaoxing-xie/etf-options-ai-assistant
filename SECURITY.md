# Security Policy

## Supported Versions

This project is currently maintained on the `main` branch.
Security fixes are applied to `main` first.

## Reporting a Vulnerability

If you find a security issue, do not open a public issue with exploit details.

- Contact maintainer via GitHub private security reporting when available.
- Or open a minimal issue asking for secure contact.
- Include affected version, reproduction steps, and impact scope.

We will acknowledge the report within 72 hours and provide an initial assessment.

## Secret Management Rules

- Never commit real tokens, API keys, webhooks, or credentials.
- Keep all sensitive values in local `.env` files only.
- Use placeholders in docs and examples (`ETF_*`, `OPENCLAW_*`).
- Rotate leaked or suspected credentials immediately.

## Hardening Checklist (Release Gate)

- No plaintext secrets in repository history and current working tree.
- No machine-specific absolute paths in published config.
- `.env.example` contains placeholders only.
- CI checks pass before release tag is created.
