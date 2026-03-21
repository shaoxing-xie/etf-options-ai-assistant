# Screenshot Assets Guide

This directory stores screenshots and demo images referenced by `README.md` and `README.en.md`.

## Minimum set for first public release

Required:

1. `gateway-health.png`
   - Content: `openclaw gateway status` key section and healthy runtime signals
2. `notification-sample.png`
   - Content: Feishu/DingTalk structured notification sample

Optional:

3. `open-10min-scenario.png`
   - Content: first-10-minutes scenario output (data summary + risk check + final action)

## Naming rules

- Use lowercase letters, numbers, and hyphens only.
- Use `.png` by default.
- Keep names stable to avoid broken README links.

## Image quality guidelines

- Recommended width: 1400-2200 px
- Font should remain readable at 100% zoom in browser
- Prefer light background unless dark theme improves readability

## Redaction and privacy checklist

Before committing screenshots, remove or mask:

- API keys, tokens, webhook URLs, app secrets
- Personal account IDs, phone numbers, email addresses
- Absolute local paths that expose private machine details
- Any production-only internal endpoint or credential material

## Update workflow

1. Export or capture screenshot
2. Redact sensitive parts
3. Save in this directory with stable filename
4. Confirm rendering in `README.md` / `README.en.md`
5. Commit together with README changes
