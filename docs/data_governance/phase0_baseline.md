# Phase0 Baseline

## Scope
- Define data contract registry, task-to-dataset mapping, and version strategy.
- Standardize `_meta` envelope fields across L3/L4 outputs.
- Keep backward compatibility by dual-write during migration window.

## Contract Rules
- All L3/L4 artifacts must include:
  - `schema_name`, `schema_version`, `task_id`, `run_id`
  - `data_layer`, `generated_at`, `trade_date`
  - `quality_status`, `lineage_refs`
- Only additive schema changes are allowed in-place.
- Breaking changes require a new schema version.

## Test Gate Checklist
- Schema files parse successfully.
- Task map covers all migrated task IDs.
- Sample artifacts can be validated against required `_meta` keys.
- No legacy reader path is broken.

## Migration Notes
- Existing artifact paths remain active until cutover.
- New semantic APIs should read standardized datasets first and fallback to legacy artifacts.
