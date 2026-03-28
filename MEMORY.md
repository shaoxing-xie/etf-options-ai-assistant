# MEMORY.md - 持久记忆与交易规则

供 memory flush 与 memory search 使用。Agent 在会话压缩前会参考此处与 dated 记忆文件，请保持更新。

**记忆双轨**：**Mem0** 对话记忆自动捕获与召回（`memory_search`）；**QMD** 本文件与 memory/*.md、workspace 文档（`qmd search` / `qmd vsearch`）。

---

## 交易与通知
- 通知渠道：飞书、钉钉群聊。
- 常用标的、阈值与工作流等可在本文件或 workspace 中按需补充。

## 工具状态

| 工具 | 状态 | 备注 |
|------|------|------|
| tool_fetch_futures_snapshot（国内） | ✅ | 东方财富数据源 |
| tool_fetch_futures_snapshot（国际） | ❌ | Yahoo Finance 受限，需配代理 |
| option_trader | ✅ | 需实盘配置 |
| tool_fetch_etf/index_realtime | ✅ | 正常 |
| tool_fetch_option_greeks | ✅ | 正常 |
| tool_fetch_index_minute | ✅ | **已修复**（2026-03-27），参数名 `period` 非 `frequency` |
| tool_fetch_etf_minute | ✅ | **已修复**（2026-03-27），510300 多周期正常 |
| tool_fetch_*_historical | ✅ | 历史日线数据正常 |
| tool_fetch_a50_data | ✅ | A50期指实时+历史数据正常（2026-03-27验证） |

## A50 期指数据验证（2026-03-27）

| 类型 | 状态 | 最新值 | 数据量 |
|------|------|--------|--------|
| 实时行情 | ✅ 成功 | 14529.0 (-0.21%) | 单条 |
| 历史行情 | ✅ 成功 | 20260327 | 6条 |
| 数据来源 | AkShare | futures_global_spot_em + futures_foreign_hist | |

## Evolution 工作流干跑测试（2026-03-28）

### 已验证工作流

| 工作流 | target | 结果 | 关键发现 |
|--------|--------|------|----------|
| research_checklist_evolution | factor_research_checklist.md | TEAM_OK | 文档存在，需增强可执行性 |
| factor_evolution | factor_momentum_20d | TEAM_OK | 因子定义在 etf_rotation_research.py:26 |
| volatility_range_evolution | 510300 | TEAM_OK | data/ 目录缺失，tavily_search 成功 |

### 关键配置文件
- `config/evolver_scope.yaml`: allowed_paths 已验证
- `docs/openclaw/execution_contract.md`: 执行契约已读取
- `workflows/*_evolution_on_demand.yaml`: 三个工作流结构正确

### 数据目录状态
- `data/prediction_records/`: ✅ 存在（1025条预测记录）
- `data/volatility_ranges/`: ✅ 存在（波动区间数据）
- `data/cache/etf_daily/510300/`: ✅ 存在（历史行情 parquet）

## 预测准确率质量评估（2026-03-28）

### 评估结果摘要
- **预测记录总数**：1025 条
- **实际行情数据天数**：625 天
- **总预测数（有匹配行情）**：1008 条
- **正确预测数**：33 条
- **准确率：3.27%** ⚠️ 极低

### 发现的严重问题

#### 1. 数据单位不一致
- 预测值存在多种单位：4.7（正确）、4700（指数点）、0.0118（未知单位）
- 同一天同标的的预测值差异巨大（4.7 vs 4700 vs 0.0118）
- 实际价格在 4.7040-4.7430 区间，但预测值范围从 0.0118 到 4759

#### 2. 所有预测记录未验证
- `verified: false` 对所有 1025 条记录
- `actual_range: null` 未填充实际值
- 缺少收盘后自动验证机制

#### 3. 预测模型问题
- 区间过宽导致"必然覆盖"或过窄导致"必然突破"
- 多个预测源（不同模型/参数）输出未统一标准化

### 修复建议（优先级排序）

| 优先级 | 修复项 | 预期效果 |
|--------|--------|----------|
| P0 | 实现预测验证定时任务 | 自动填充 actual_range |
| P0 | 添加数据标准化层 | 统一预测值单位 |
| P1 | 添加预测质量门禁 | 拒绝不合理预测值 |
| P1 | 实现多模型融合验证 | 提高预测准确率 |
| P2 | 添加预测回测报告 | 持续监控准确率趋势 |

## Cron任务修复记录（2026-03-28）

### 投递渠道已修复（飞书 → 钉钉）
以下4个任务已将投递渠道从飞书改为钉钉：
- `9d8e5b7d-f7b1-4116-ac02-055598a74781`: etf: 早盘数据采集
- `b10b4155-5ca6-43c6-b910-9d68b6d1e748`: etf: 盘中数据采集-5分钟-收盘
- `ops-system-health-check`: shared: 系统健康检查
- `llm-health-monitor`: shared: LLM 模型健康巡检

新配置：`delivery.channel: "dingtalk"`, `to: "cid80wtHkZBVK4LHSeKj6N52g=="`

### 超时任务待修复
以下2个任务需要增加超时时间：
- `3535ccab-f974-44ad-a642-c28964a89942` (price-alert-polling): 建议设为120秒
- `c4f8a2e1-9b0d-4c7e-8f3a-2d6e1b9c5a70` (etf: 策略引擎与信号融合): 建议设为180秒

## AUTOFIX 执行完成（2026-03-28 08:25）

### 波动率区间预测参数调整

| 参数 | 修改前 | 修改后 | 文件位置 |
|---|---|---|---|
| min_intraday_pct | 0.5% | 1.5% | plugins/analysis/intraday_range.py:48 |
| lookback_days | 15 | 10 | plugins/analysis/intraday_range.py:141 |
| primary_weight (30min) | 0.7 | 0.6 | src/volatility_range.py:565,889 |
| secondary_weight (15min) | 0.3 | 0.4 | src/volatility_range.py:566,890 |
| 窄区间置信度降权 | 无 | <1.5%时降权20% | plugins/analysis/intraday_range.py:89,218 |

### Git 提交
- Commit: 6254e7d
- 备份文件: `*.py.bak`

## 期货数据工具澄清（2026-03-14）

**⚠️ 重要：系统期货数据能力边界**

| 类型 | 状态 | 工具/说明 |
|------|------|-----------|
| **股指期货（A50期指）** | ✅ 可用 | `tool_fetch_a50_data` |
| **商品期货（沪金/原油/螺纹等）** | ❌ **未实现** | 系统暂无商品期货数据采集工具 |

## 钉钉用户信息（私信/群内 @）

| 用户名 | open_id（钉钉） | 群聊 conversation_id | 备注 |
|--------|-----------------|----------------------|------|
| 谢富根 | `055062293235230095` | `cid0dqwayvqu94+qeoodxl1uw==` | 群内可直接回复 |
| 邬华阳 | `013334132836291153` | 同上 | |
| 姜丹灵 | `176754005922756408` | 同上 | |

## 价格预警（2026-03-13）
- 存储：`data/alerts.json`；Cron `price-alert-polling` 每 10 分钟（交易时段）。
- 通知：钉钉群内 @ 或私信（需用户已开启私聊）。
- 指令：`#预警 代码 条件 目标值`；每人最多 5 条，触发后自动取消。

## 输出规范
盘前/盘后/信号分析报告结构、表格与 emoji 规范见 **`docs/输出规范.md`**。

## 标的池配置约定（2026-03-14 重要）

**⚠️ 所有"当前系统配置的标的清单/行业ETF列表/宽基池"等问题，一律以 `config/symbols.json` 为准**

| 文件 | 作用 |
|------|------|
| `config/symbols.json` | 统一管理指数/ETF/期指/期权底层标的池及优先级 |
| `src/symbols_loader.py` | Python加载器，提供统一API |

### 分组结构
- **core**（high）：核心宽基池，盘中高频采集
- **industry_etf**（medium）：行业/主题ETF池
- **futures**（medium）：股指与商品期货
- **options_watchlist**（low）：期权底层标的关注池

## GitHub Actions 维护（2026-03-27）

**release-gate 工作流修复**：
- 失败原因：`scripts/test_mootdx_index_realtime.py` 硬编码绝对路径
- 修复：`9ee39ac fix: remove absolute path leak`
- 验证：新运行 `23621527878` 成功通过

**新增技能**（2026-03-27 通过 clawhub 安装）：
- `skills/agent-team-orchestration`
- `skills/capability-evolver`

---

_记忆已于 2026-03-07 重置；输出规范于 2026-03-10 更新；工具状态于 2026-03-14 更新；GitHub Actions 修复于 2026-03-27 更新；Evolution 干跑测试于 2026-03-28 更新；预测准确率评估于 2026-03-28 更新。_

## 预测系统优化建议（2026-03-28）

### 优化意愿
基于预测准确率评估结果（3.27%），系统存在以下优化需求：
1. **数据标准化**：统一预测值单位，消除数据不一致问题
2. **验证机制**：实现收盘后自动验证流程
3. **质量门禁**：拒绝不合理预测值
4. **监控体系**：建立预测准确率持续监控

### P0 优化（立即执行）

**1. 实现预测验证定时任务**
- 时间：每日 15:30 执行
- 功能：读取当日实际行情，填充 `actual_range`，标记 `verified: true`
- 预期效果：100% 预测记录得到验证

**2. 添加数据标准化层**
- 功能：自动检测并转换预测值单位（指数点 → ETF价格 → 百分比）
- 预期效果：消除单位不一致问题（当前存在 4.7 vs 4700 vs 0.0118 混用）

### P1 优化（本周完成）

**3. 添加预测质量门禁**
- 规则：区间宽度≥1%、上下限合理、价格范围在 3-6 元
- 预期效果：拒绝不合理预测，提升数据质量

**4. 实现多模型融合验证**
- 功能：按历史准确率加权合并多个预测源
- 预期效果：提高预测稳健性

### P2 优化（下周完成）

**5. 添加预测回测报告**
- 功能：每日生成准确率趋势报告
- 预期效果：持续监控预测质量

**6. 建立预测质量监控仪表板**
- 指标：准确率、覆盖率、突破率、单位一致性
- 输出：钉钉日报 + 内存存储

### 实施路径

| 阶段 | 时间 | 内容 | 预期效果 |
|------|------|------|----------|
| 第1阶段 | 下周一 | P0 优化（验证任务+标准化） | 准确率提升至 20%+ |
| 第2阶段 | 下周三 | P1 优化（质量门禁+融合验证） | 准确率提升至 40%+ |
| 第3阶段 | 下周五 | P2 优化（回测报告+仪表板） | 持续监控体系建立 |

---
_EOF
echo "MEMORY.md 已追加优化建议"
