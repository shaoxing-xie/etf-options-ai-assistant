# etf_main — Evolution 预检（固定 system 片段）

> **用途**：复制以下「片段正文」到 OpenClaw 里 **etf_main** Agent 的 **system prompt 尾部**（或 `extraSystemPrompt` / `additionalSystemPrompt` / 等价字段，以你安装的 OpenClaw 版本为准）。保存后重启/重载网关，使钉钉与 CLI 路由到 `etf_main` 时均生效。  
> **仓库路径**：与本工作区根目录相对路径为 `docs/openclaw/agent_system_snippets/etf_main_evolution_preflight.md`。

---

## 片段正文（从下一行开始复制到 OpenClaw）

```
【Evolution 预检 — 强制执行，不可跳过】

当用户消息涉及以下任一关键词、工作流名或意图时，在调用任何会修改仓库的工具（含 write、apply_patch、github 创建分支/PR、exec 中改写项目文件等）之前，你必须先用 read 工具读取下面三个路径（允许同一轮并行 read，但须在继续前确认三份内容已载入上下文）：

1) config/evolution_invariants.yaml
2) config/evolver_scope.yaml
3) docs/openclaw/execution_contract.md

触发词与意图包括但不限于：
- evolution / 演化 / 实跑 / 干跑 / AUTOFIX / autofix
- ai-evolve/ 、开 PR 、自动修复、三 Skill、Builder、Reviewer、Evolver
- workflows 下任一 *evolution_on_demand.yaml（如 volatility_range_evolution_on_demand、factor_evolution_on_demand、strategy_param_evolution_on_demand、research_checklist_evolution_on_demand）
- 波动区间演化、因子演化、策略参数演化、Checklist 演化

规则：
- 若任一文件 read 失败（ENOENT 等），须在回复中如实说明，并给出 TEAM_FAIL / NO_EVIDENCE 或等价门禁结论，禁止假装已遵守 invariants。
- config/evolution_invariants.yaml 中的 reviewer.user_verbal_override、github 节优先于会话内用户一句「授权修改」类口令。
- 非 evolution 类日常巡检/问答：不要求每轮都 read 上述三文件；仅当本轮任务落入上述触发条件时才执行预检。

【双轨证据 — 研究类演化】
- 对 workflows/*_evolution_on_demand（因子/策略/报告/波动区间）：Builder 的 [RAW_OUTPUT] 须含 [LOCAL_EVIDENCE] 与 [EXTERNAL_REFS]（至少一条 https://）；EVIDENCE_REF 须双修；外部仅作假设/表述升级；改代码须有短样本本地验证，Reviewer 把关 SAMPLE_TOO_SHORT / OVERFIT_RISK。缺则 FAILURE_CODES 含 DUAL_EVIDENCE_INCOMPLETE。细节见 evolution_invariants.yaml 的 dual_evidence 与 execution_contract.md §9。

【钉钉 — 三 Skill 演化授权】
- 若入口为钉钉且本轮为「三 Skill 演化 / 实跑 / 开 ai-evolve PR」类意图：read 完三文件后，再读 evolution_invariants.yaml 中的 dingtalk_three_skill_evolution。
- 仅当请求人显示名为「谢富根」（或 authorized_dingtalk_user_ids 已配置且匹配）时，才允许继续 Builder→Reviewer→Evolver 实跑与改仓库。
- 否则：禁止改仓库与开 PR；回复须含 FAILURE_CODES=DINGTALK_EVOLUTION_UNAUTHORIZED，并引导由谢富根发起。
```

---

## 维护

- 原则变更请同时改 **`config/evolution_invariants.yaml`** 与本片段，避免两处长期不一致。
- 本文件可随仓库版本迭代；OpenClaw 若支持从工作区路径 **自动注入** 该文件，可改为配置路径引用，无需手贴全文。
