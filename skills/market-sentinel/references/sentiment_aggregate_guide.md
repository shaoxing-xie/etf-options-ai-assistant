# 情绪聚合说明（market-sentinel）

- 四工具并行拉取后做证据归一，再按 `market-sentinel_config.yaml` 的权重与 `risk_mode` 计算综合分。
- `sentiment_stage` 含冰点、修复、高潮、退潮、震荡、混沌；**默认 overall_score 区间映射**见配置中 `sentiment_stage_thresholds`，与 `docs/sentiment/api_contract.md` 的 Skill aggregate 表一致。
- 若四分项极差 ≥ `chaos_subscore_spread_min`，阶段可覆盖为 **混沌**，并在 `factor_attribution.notes` 说明。
- 任一子源失败时：重标化可用项权重，填写 `risk_counterevidence` 与 `data_completeness_ratio`，仍使用统一输出模板（`degraded: true`）。
