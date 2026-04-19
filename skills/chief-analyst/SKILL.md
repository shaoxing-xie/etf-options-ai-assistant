---
name: chief-analyst
description: Orchestrate multiple analysis skills and surface agreement vs conflict (no extra data fetch).
---

# Chief analyst (orchestration)

## Role

Coordinate **read-only** calls to existing skills in a fixed order; do **not** add new scraping or bypass `openclaw-data-china-stock` tools.

## Recommended call order

1. `market-scanner` — trading status + breadth / flow snapshot  
2. `technical-analyst` — default indicator bundle from `technical-analyst_config.yaml`  
3. `fund-flow-analyst` — northbound + sector + main force context  
4. `china-macro-analyst` — `tool_fetch_macro_snapshot` first, then `tool_fetch_macro_data` if gaps  
5. `market-sentinel` / sentiment aggregate when scheduled narrative is required  

## Output shape

Return a short JSON-friendly block:

- `consensus`: one of `risk_off` | `neutral` | `risk_on`  
- `conflicts`: list of strings (empty if aligned)  
- `fused_confidence`: copy from `src.tool_payload_quality.fused_confidence_hint` when numeric inputs exist  
- `evidence_tools`: list of tool ids actually used  

## Constraints

- Respect workspace rules: do not edit `~/.openclaw/extensions/openclaw-data-china-stock/**`.  
- If any dependency returns `quality_score` below `config/data_quality_policy.yaml` → `quality_score.warn_below`, prepend the quality warning string from `quality_warn_message`.
