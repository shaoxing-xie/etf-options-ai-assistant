# Trading Journal Schema (v1)

This project maintains an append-only JSONL journal at:

- `data/trading_journal/events.jsonl`

Each line is a single JSON object with the following envelope:

```json
{
  "schema_version": "trading_journal.v1",
  "ts": "2026-03-06T14:48:45+08:00",
  "event_type": "signal_recorded",
  "actor": "tool_record_signal_effect",
  "payload": { }
}
```

## event_type: signal_recorded

Payload fields (best-effort; may be null for partial updates):

- `signal_id`
- `date`
- `timestamp`
- `signal_type`
- `symbol`
- `signal_strength`
- `strategy`
- `entry_price`
- `exit_price`
- `profit_loss`
- `profit_loss_pct`
- `holding_days`
- `status`
- `exit_reason`
- `source`

## event_type: strategy_fusion（可选，additive）

由 `tool_strategy_engine` 在成功融合后追加。Payload 建议字段：

- `policy_version`
- `weights_effective`
- `candidates`（摘要列表或完整结构，注意体积）
- `fused`（融合结果 dict）
- `inputs_hash`（与引擎输出一致）

Notes:
- Journal write failures must **never** break trading tools. It's a side-channel for observability and replay.
- This schema is intentionally stable and minimal. Additive changes only.

