# Internal Alert Weekly Review Template

## 1) Scope

- Review window: `<YYYY-MM-DD>` to `<YYYY-MM-DD>`
- Mode: `observe | semi_auto | auto`
- Symbols covered: `<510300,510500,...>`

## 2) Technical Reliability

- Alert chain success rate: `<%>`
- Scan-to-store P95 latency: `<ms>`
- Trigger-to-fusion P95 latency: `<ms>`
- Dedup interception rate: `<%>`
- Cooldown skip count: `<n>`

## 3) Alert Quality

- Total events: `<n>`
- Triggered events: `<n>`
- Noise ratio (`invalid_or_skipped / total`): `<%>`
- Group effectiveness:
  - technical: `<%>`
  - volatility: `<%>`
  - regime: `<%>`
- Priority breakdown:
  - high: `<n>`
  - medium: `<n>`
  - low: `<n>`

## 4) Fusion Contribution

- Source contribution average:
  - src_signal_generation: `<%>`
  - etf_trend_following: `<%>`
  - internal_chart_alert: `<%>`
- Notable cases:
  - `<inputs_hash>`: `<summary>`

## 5) Risk & Operations

- Circuit breaker / emergency override triggers: `<n>`
- No-Go redline hits: `<n>`
- Incidents and MTTR: `<details>`

## 6) Decision (Go/No-Go)

- Decision: `Go | No-Go`
- Reason:
  - `<evidence-based bullets>`
- Next-week actions:
  - `<action 1>`
  - `<action 2>`

