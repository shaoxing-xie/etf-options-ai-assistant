# 情绪驱动 cron 上线与回滚

适用范围：

- `workflows/pre_market_sentiment_check.yaml`
- `workflows/opening_analysis.yaml`
- `workflows/intraday_analysis.yaml`
- `workflows/daily_market_report.yaml`
- `workflows/extreme_sentiment_monitor.yaml`

## 本地/CI 验证

在仓库根执行：

```bash
python3 scripts/validate_workflows.py
python3 scripts/validate_agent_yaml_tools.py
python3 scripts/render_agents_config.py --apply-jobs
python3 scripts/validate_agent_skill_matrix.py
python3 tests/integration/run_all_workflow_tests.py
```

## 观察指标（上线后 1 周）

- `pre_market_sentiment_check` 成功率
- `pre_market_sentiment_check` 降级率（`degraded=true`）
- `extreme_sentiment_monitor` 触发次数 / 误报数
- 开盘报告、盘中巡检、盘后日报中“情绪归因”字段缺失率
- `insufficient_evidence` 占比
- `sentiment_dispersion` 高值占比（建议阈值：stddev>=18 或 spread>=35）
- `sentiment_meta.sentinel_version` / `weight_profile` 覆盖率（应接近 100%）
- 分时段缓存命中表现（opening/mid/closing 三档 TTL）

## 回滚开关（运维级）

若情绪链路导致误报、拖慢执行或引入噪音，按以下顺序回滚：

1. 先停新增任务：
   - 禁用 `pre-market-sentiment-check`
   - 禁用 `extreme-sentiment-monitor`
2. 保留现有主链路，但将情绪结论视为旁路背景：
   - `opening_analysis` 与 `intraday_analysis` 保留四工具采集，忽略门禁叙事
3. 如仍需彻底回滚：
   - 回退本次 workflow YAML 变更
   - 运行：

```bash
python3 scripts/render_agents_config.py --apply-jobs
python3 scripts/validate_agent_skill_matrix.py
```

说明：当前回滚开关以**任务级禁用**为主，而非单独运行时布尔变量；这样风险最小，不影响既有工具与 agent 技能装配。

## 建议输出扩展（版本与分歧度）

情绪聚合结果建议统一附加：

- `sentiment_meta`:
  - `sentinel_version`（如 `v0.5.3`）
  - `weight_profile`（如 `default` / `short_term_game` / `institutional_view`）
  - `generated_at`
- `sentiment_dispersion`：
  - 优先 `stddev`（四子项标准差）
  - 兜底 `spread = max(sub_scores)-min(sub_scores)`

盘中缓存策略（建议）：

- `opening_first_hour`: 300 秒
- `mid_session`: 900 秒
- `closing_hour`: 600 秒
