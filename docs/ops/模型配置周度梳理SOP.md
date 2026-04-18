# 模型配置周度梳理 SOP（OpenClaw / ETF 分析系统）

本文用于把“每周模型梳理”标准化，避免反复人工试错。目标是：**快速识别不稳定模型、完成全量配置对齐、保证回滚可控**。

---

## 1. 适用范围

- `~/.openclaw/openclaw.json`
- `~/.openclaw/agents/**/agent/models.json`
- `etf-options-ai-assistant/config/domains/outbound.yaml`
- 仅修改配置层，不修改运行时插件代码（遵守边界规则）。

---

## 2. 一次梳理的标准步骤

### Step A：采样测试（事实先行）

1. 运行批测脚本：
   - `MODEL_TEST_TIMEOUT=40 ~/scripts/test-openclaw-models-batch.sh`
2. 记录结果到三类：
   - **稳定**：`HTTP 200`（建议至少连续 2~3 次）
   - **降级**：`429` / `timeout`（先降权到 fallback 后位）
   - **清除**：`404` / `410` / 持续 `400`（直接移除）

> 经验：不要用“独立临时脚本 + 当前 shell 环境”替代该批测脚本结论；必须使用同源配置加载链路（`openclaw.json + .env`）。

### Step B：确定本周模型池

1. **分析主池（NVIDIA）**：保留 5 个主力模型（双 provider）。
2. **OpenRouter free 池**：只保留本周稳定项；不稳定项移除或降级。
3. 新增候选必须先探测（至少 3 次），再入池。

### Step C：路由规则编排

1. **分析 agent**
   - `primary`：NVIDIA
   - `fallbacks`：第 1 个 OpenRouter，第 2 个 NVIDIA，之后交替（OR/NV/OR/NV...）
2. **非分析 agent**
   - `primary`：OpenRouter
   - `fallbacks`：第 1 个 NVIDIA，第 2 个 OpenRouter，之后交替（NV/OR/NV/OR...）

### Step D：全量对齐修改

按顺序改：

1. `openclaw.json`
   - `models.providers.*.models`（模型目录）
   - `agents.defaults.models`（别名映射）
   - `agents.list[*].model.primary/fallbacks`（实际路由）
2. `~/.openclaw/agents/**/agent/models.json`
   - provider 模型目录与 `openclaw.json` 对齐
3. `config/domains/outbound.yaml`
   - 默认模型别名同步更新（移除废弃别名）

### Step E：验收与收口

1. JSON/YAML 语法校验通过。
2. 搜索校验：
   - 废弃模型（如 `deepseek-v3.1`、本周清除项）在**生效配置文件**中为 0。
3. 再跑一次批测脚本，确认路由主链可用。

---

## 3. 错误码处置策略（推荐）

- `200`：可用，保留
- `429`：暂时限流，降权但可保留
- `timeout`：先降权；连续两周超时则移除
- `404`：直接移除（无端点）
- `410`：直接移除（EOL）
- `400`（持续同类错误）：视为不可用，移除

---

## 4. 本项目当前实践约束（必须遵守）

- 不改运行时插件目录（`~/.openclaw/extensions/openclaw-data-china-stock/**`）。
- 所有修改都在 assistant 工程与 OpenClaw 配置层完成。
- 历史日志里出现旧模型不代表当前配置未生效；只检查生效配置文件。

---

## 5. 周度执行清单（Checklist）

- [ ] 跑 `test-openclaw-models-batch.sh` 并分组稳定/降级/清除
- [ ] 确定本周 NVIDIA 主池 + OpenRouter free 稳定池
- [ ] 应用分析/非分析交替规则
- [ ] 同步 `openclaw.json`、`agents/**/models.json`、`outbound.yaml`
- [ ] 校验 JSON/YAML 与废弃模型清零
- [ ] 再测并输出“主链 + 前5 fallback”验收表

---

## 6. 给助手的标准指令模板（可直接复用）

```text
按 docs/ops/模型配置周度梳理SOP.md 执行本周模型梳理：
1) 先跑 MODEL_TEST_TIMEOUT=40 ~/scripts/test-openclaw-models-batch.sh，按 200/429/timeout/404/410 分组；
2) 清除本周不可用模型并给出替代（先测试再入池）；
3) 分析agent：primary=NVIDIA，fallback 从 OpenRouter 开始交替；
4) 非分析agent：primary=OpenRouter，fallback 从 NVIDIA 开始交替；
5) 同步修改 ~/.openclaw/openclaw.json、~/.openclaw/agents/**/agent/models.json、config/domains/outbound.yaml；
6) 输出：变更清单 + 剩余风险 + 再测结果。
```

---

## 7. 本次复盘（关键教训）

1. **先测再改**，否则会在“模型可用性假设”上反复返工。
2. **统一环境链路**，避免因 shell 环境变量不同导致误判。
3. **路由与目录必须双对齐**，只改 fallback 不改 provider models 会留下悬挂引用。
4. **一次性全局替换 + 最终校验**，避免局部修补反复回归。

