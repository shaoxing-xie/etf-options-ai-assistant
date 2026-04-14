## Summary

<!-- 简述改动与动机 -->

## `plugins/notification/**`（展示层 / 钉钉长文）

若本 PR **修改** `plugins/notification/` 下任意文件（含 `send_daily_report`、标题/章节/合并逻辑等），**合并前请在 PR 描述或首条评论中写明一行**：

```text
AUTOFIX_ALLOWED=false
```

与 `config/evolver_scope.yaml` 中 `denied_paths` → `plugins/notification/**`、`docs/research/daily_market_report_web_benchmark.md` §3 及 Evolver 门禁一致，避免被误当作可自动修复路径。

- [ ] 本 PR **不涉及** `plugins/notification/**`
- [ ] 本 PR **涉及** `plugins/notification/**`，且已在描述或首评标注 `AUTOFIX_ALLOWED=false`

## Checklist

- [ ] 本地可运行 / 关键路径已自测（如适用）
- [ ] 未提交密钥与硬编码私密配置
- [ ] 行为变更已更新相关文档（如适用）
