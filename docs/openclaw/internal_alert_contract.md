# Internal Alert Contract (OpenClaw Native)

## Purpose

This document defines the internal chart-alert contract used by the OpenClaw native "TradingView-like" pipeline.
It standardizes:

- alert rule schema (`AlertRule`)
- trigger event schema (`InternalAlertEvent`)
- deduplication and cooldown policy
- response and error conventions for ingest/scan flows

## Versioning

- `contract_version`: required in both rule and event objects
- Current version: `1.0`
- Breaking changes must increment major version (`2.0`, `3.0`, ...)

## AlertRule Schema

```json
{
  "rule_id": "rsi_oversold_510300_30m",
  "contract_version": "1.0",
  "enabled": true,
  "symbol": "510300",
  "timeframe": "30m",
  "group": "technical",
  "priority": "medium",
  "condition": {
    "type": "threshold",
    "metric": "rsi",
    "operator": "<=",
    "value": 30
  },
  "cooldown_sec": 300,
  "ttl_sec": 86400,
  "notify": {
    "channels": ["feishu", "dingtalk"],
    "template": "default"
  },
  "actions": {
    "emit_signal_candidate": true
  },
  "metadata": {
    "owner": "analysis_team",
    "tags": ["mvp", "observe"]
  }
}
```

## InternalAlertEvent Schema

```json
{
  "event_id": "evt_20260407_510300_rsi_oversold_30m_001",
  "contract_version": "1.0",
  "source": "internal_chart_alert",
  "rule_id": "rsi_oversold_510300_30m",
  "symbol": "510300",
  "timeframe": "30m",
  "trigger_ts": "2026-04-07T10:30:00+08:00",
  "bar_ts": "2026-04-07T10:30:00+08:00",
  "group": "technical",
  "priority": "medium",
  "condition_snapshot": {
    "metric": "rsi",
    "operator": "<=",
    "value": 30,
    "actual": 27.4
  },
  "dedup_key": "internal_chart_alert|510300|30m|rsi_oversold_510300_30m|2026-04-07T10:30:00+08:00",
  "status": "triggered",
  "metadata": {
    "scan_id": "scan_20260407_103000",
    "mode": "observe"
  }
}
```

## Required Fields

For `AlertRule`:

- `rule_id`, `contract_version`, `enabled`, `symbol`, `timeframe`, `group`, `priority`
- `condition.type`, `condition.metric`, `condition.operator`, `condition.value`
- `cooldown_sec`, `ttl_sec`

For `InternalAlertEvent`:

- `event_id`, `contract_version`, `source`, `rule_id`, `symbol`, `timeframe`
- `trigger_ts`, `bar_ts`, `group`, `priority`, `dedup_key`, `status`

## Enumerations

- `group`: `technical` | `volatility` | `regime`
- `priority`: `high` | `medium` | `low`
- `status`: `triggered` | `dedup_skipped` | `cooldown_skipped` | `invalid`
- `condition.operator`: `>` | `>=` | `<` | `<=` | `==` | `!=`

## Deduplication and Cooldown

### Dedup Key

Canonical format:

`source|symbol|timeframe|rule_id|bar_ts`

### Dedup Rules

- If same `dedup_key` exists within `ttl_sec`, skip with `status=dedup_skipped`.
- Keep first event as canonical and link duplicates by `metadata.duplicate_of`.

### Cooldown Rules

- Cooldown scope: by default `(rule_id, symbol)`.
- If current time is within `cooldown_sec` from latest `triggered` event, skip with `status=cooldown_skipped`.

## Ingest/Scan Response Conventions

Success response:

```json
{
  "success": true,
  "message": "internal alert processed",
  "data": {
    "event_id": "evt_xxx",
    "status": "triggered"
  }
}
```

Failure response:

```json
{
  "success": false,
  "message": "validation failed: missing rule_id",
  "error_code": "BAD_REQUEST",
  "data": null
}
```

## Error Code Guidelines

- `BAD_REQUEST`: schema/field validation error
- `UNAUTHORIZED`: signature/auth failed (if external ingest exists later)
- `TOO_MANY_REQUESTS`: rate limited
- `INTERNAL_ERROR`: unhandled execution error

## Audit Requirements

Each event record should keep:

- `event_id`, `rule_id`, `symbol`, `timeframe`, `group`, `priority`
- `dedup_key`, `status`, `trigger_ts`, `ingested_ts`
- `scan_id`, `mode`, `notify_result`, `fusion_result_ref` (if available)

## Backward Compatibility

- Readers must tolerate unknown fields.
- Writers should not remove required fields in same major version.
