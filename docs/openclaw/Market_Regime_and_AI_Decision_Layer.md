# 市场状态识别与 AI 决策层设计（OpenClaw v2.1）

## 1. 设计目标

- 在不破坏现有「研究模式一 + etf_* Agents + 钉钉/飞书渠道」前提下，为系统增加两层能力：
  - **Market Regime 识别层**：识别当前市场处于趋势/震荡/高风险等状态。
  - **AI 决策层（AI Decision Layer）**：在 Regime、策略表现与风险约束的基础上，给出策略启用/停用与权重建议。
- 所有新增能力默认作为「研究与决策建议」，**不直接改动线上策略参数或仓位**，由人工审核后再执行。

## 2. 与现有架构的关系

整体架构示意（精简版）：

```mermaid
flowchart TD
  subgraph dataLayer [Data Layer]
    dataCollector[etf_data_collector_agent]
  end

  subgraph analysisLayer [Analysis Layer]
    trendVol[趋势与波动分析\n(before_open/opening/after_close/intraday)]
  end

  subgraph regimeLayer [Market Regime Layer]
    marketRegimeAgent[market_regime_agent\n(逻辑角色)]
  end

  subgraph decisionLayer [AI Decision Layer]
    aiDecision[ai_decision_layer\n(策略/权重建议)]
  end

  subgraph coreLayer [Core Logic Layer]
    businessCore[etf_business_core_agent]
    riskAgent[risk_agent\n(env + risk_check)]
  end

  subgraph notifyLayer [Notification Layer]
    notify[etf_notification_agent\n(沿用钉钉/飞书渠道)]
  end

  dataCollector --> trendVol
  trendVol --> marketRegimeAgent
  marketRegimeAgent --> aiDecision
  aiDecision --> businessCore
  businessCore --> riskAgent
  riskAgent --> notify
```

> 说明：本文件中的 `market_regime_agent` 与 `ai_decision_layer` 先作为**逻辑角色**存在，后续如有需要再拆分为独立 Agent/工具文件。

## 3. Market Regime 识别（market_regime_agent）

### 3.1 输入来源

- 现有分析结果 JSON（已通过工具 + LLM 增强生成）：
  - 盘前分析：`before_open`（全球/盘后 + A50 + 预期开盘区间）。
  - 开盘分析：`opening_market`（集合竞价 + 开盘量价结构）。
  - 盘后分析：`after_close`（当日整体趋势与成交结构）。
  - 波动预测：`volatility_prediction_underlying` / `volatility_prediction_option`。
  - 盘中快照：`intraday_summary` / `signal_watch` 等。
- 数据层特征：
  - 指数/ETF 日内与日线收益率、盘中区间位置、连续涨跌天数。
  - 历史/预测波动率、IV percentile、回撤幅度。

### 3.2 Regime 输出结构（建议）

```json
{
  "regime": "trending_up | trending_down | range | high_vol_risk | low_vol_silent",
  "confidence": 0.7,
  "features": {
    "index_trend": "up",
    "trend_strength": 0.8,
    "realized_vol": 0.22,
    "iv_percentile": 0.65,
    "drawdown_pct": -0.03
  },
  "comment": "示例：短期趋势向上，波动中高，适合趋势/轮动策略的小仓位尝试。"
}
```

> 初期可以通过规则 + 现有分析 JSON + LLM 解读来生成上述结构；后续如需引入更复杂模型（GARCH/HMM/ML），仅需在实现层替换，而不改变输出接口。

### 3.3 与研究模式一的关系

- Regime 识别逻辑应视为「研究模式一」下的一部分研究结论：
  - 在盘前/盘后/盘中总结中增加「市场状态」小节，例如：趋势/震荡/高风险等。
  - 在**高密度要点总结**中加入 1 条关于 Regime 的浓缩描述（方便 byterover 写入记忆）。
- 所有 Regime 结论必须遵守研究模式一的通用要求：
  - 明确数据来源与假设；
  - 不夸大结论的稳定性；
  - 提供潜在失效场景与风险提示。

## 4. AI 决策层（ai_decision_layer）

### 4.1 职责

- 综合以下信息，给出策略/权重建议：
  - 当前 Market Regime 输出（趋势/震荡/高风险等）。
  - 策略研究工作流（`strategy_research`）输出的最新策略评分与历史表现。
  - 当前风控约束与风险敞口（通过 `env` + `risk_check` 间接获得）。
- 输出以**“建议方案”**形式写入研究报告和巡检报告，供人工审核：
  - 建议启用/暂停哪些策略；
  - 建议的策略权重区间（在现有权重基础上的微调幅度）；
  - 适配当前 Regime 的仓位上限区间（仍需 risk_engine 最终拍板）。

### 4.2 输出示例

```json
{
  "strategy_recommendations": [
    {
      "strategy": "trend_following",
      "action": "increase_weight",
      "delta_weight": 0.1,
      "reason": "当前为趋势市，上行趋势强度高，且该策略在类似 Regime 下历史表现优异。"
    },
    {
      "strategy": "mean_reversion",
      "action": "decrease_weight",
      "delta_weight": -0.1,
      "reason": "当前非典型震荡市，均值回归策略在历史上此类环境中表现一般。"
    }
  ],
  "position_guidance": {
    "overall_max_risk_pct": 0.15,
    "per_strategy_max_risk_pct": {
      "trend_following": 0.08,
      "mean_reversion": 0.04,
      "breakout": 0.03
    },
    "comment": "以上为研究建议，实际执行仍以 risk_engine 评估与人工审核为准。"
  }
}
```

### 4.3 与现有工具/工作流的衔接

- `workflows/strategy_research.yaml`：
  - 在生成策略研究报告时，可增加一小节「Regime × 策略表现矩阵」；
  - 在此基础上由 ai_decision_layer 给出权重调整建议与启用/停用建议。
- 工作流A（信号 + 风控巡检）：
  - 在 Feishu/DingTalk 巡检报告中，可以追加一行简短说明当前 Regime 与策略推荐状态；
  - 不直接更改实际下单逻辑，仅作为合规友好的「研究与巡检附加视角」。

## 5. 钉钉/飞书渠道与研究模式一的一致性

- 所有涉及 Regime 与 AI 决策层的输出：
  - 继续通过 `etf_notification_agent` → 现有 Feishu Webhook/插件 → 映射到钉钉/飞书现有群；
  - 不新增新的推送渠道，保持运维与使用体验一致。
- Markdown 输出规范继续沿用 `~/.openclaw/prompts/research.md` 中的要求：
  - 统一使用标准 Markdown，兼容钉钉/飞书；
  - 结构化输出 + 高密度要点总结；
  - 明确标注「以上内容仅供研究参考，不构成投资建议」。

