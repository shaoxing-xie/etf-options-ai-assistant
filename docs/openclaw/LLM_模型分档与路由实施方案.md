# LLM 模型分档与路由实施方案（OpenClaw / etf-options-ai-assistant）

本文用于指导你在 OpenClaw 体系内，为不同 **agent / job / workflow** 配置合适的模型档位、降级策略与成本控制手段，作为长期可查询的“配置决策依据”。

> 注意：本方案**不包含**任何 API Key / provider 私密信息。具体 provider 配置请查看各 agent 目录下的 `agent/models.json`（仅本机使用，避免提交到公开仓库）。

---

## 目标与约束

- **目标**：在“稳定交付（格式/合规/工具调用）”与“成本/速度”之间取得可控平衡；出现 provider 波动/配额/403 时能自动降级，不让业务任务长时间 silent fail。
- **约束**：交易时段高频任务必须优先稳定；强模板任务必须优先指令遵循；研究型长文必须优先推理质量与上下文容量。

---

## 一、按工作任务类别分档（推荐的统一口径）

建议将所有任务先归入下面 5 类之一，再决定模型档位与回退策略：

### 1) 工具编排 / 数据搬运型（高频、确定性强）
**特征**：主要是调用工具、落盘、少量字段拼装；推理深度低；容错策略是“失败即降级/跳过/重试一次”。  
**典型**：分钟线/日线采集、开盘数据拉取、缓存读取 + 指标计算前置。  
**优先级**：速度/成本 > 推理质量。

### 2) 结构化巡检快报型（强模板、强约束、低容错）
**特征**：输出必须严格匹配模板（甚至“只能输出模板本体”）；宁可少说也不能多说。  
**典型**：`信号+风控巡检` 三个时段快报、阈值触发类提示。  
**优先级**：指令遵循/格式稳定 > 速度 > 推理质量。

### 3) 研究报告 / 策略推理型（长文本、多步骤、综合判断）
**特征**：多源信息整合、长链路推理、较长 Markdown 报告；需要稳定的长上下文与“低幻觉表达”。  
**典型**：盘前/盘后完整分析、日报、轮动研究、策略研究与回放、涨停回马枪盘后报告。  
**优先级**：推理质量/长上下文 > 稳定性 > 成本。

### 4) 运维监控 / 日志解析告警型（解析+聚合，成本敏感）
**特征**：以本地 JSON/JSONL 解析、聚合阈值判断为主；尽量减少 LLM tokens。  
**典型**：系统健康检查、LLM 健康巡检、近期运行失败聚合。  
**优先级**：确定性/低成本 > 语言质量。

### 5) 工具链体检总结型（外部工具输出 → 摘要/优先级）
**特征**：读取 ruff/mypy/pytest/bandit 的输出，生成“问题分级 + 修复优先级 + 建议 diff（不落盘）”。  
**典型**：每日代码健康体检。  
**优先级**：理解工具输出与归因能力 > 成本。

---

## 二、统一模型档位定义（F / M / S）

为了让“将来新增任务”可快速配置，建议统一维护三档模型：**F（Fast）/ M（Medium）/ S（Strong）**。

### F 档（Fast：高频/低成本/工具编排优先）
- **适用**：类别 1、类别 4 的绝大多数任务。
- **特征**：便宜/快；不追求长篇表达；失败要快速切换。
- **推荐候选（从当前 `models.json` 可见的模型 id 中挑选）**：
  - `stepfun/step-3.5-flash:free`
  - `gemini-2.5-flash` / `gemini-3-flash-preview`
  - 本地 `qwen2.5:3b`（若本机稳定、且你能接受效果波动）

### M 档（Medium：模板遵循/稳健推理/中等成本）
- **适用**：类别 2、类别 5，以及类别 3 的“短报告/低风险版本”。
- **特征**：更稳的指令遵循，适合强模板输出与较严格的结构化文本。
- **推荐候选**：
  - `glm-5`（iflow2api）
  - `deepseek-v3.2-chat`（iflow2api）
  - `deepseek-chat`（DeepSeek 官方 32k：适合较长文本但注意可用性/配额）

### S 档（Strong：研究级/长链路/容错强）
- **适用**：类别 3（盘前/盘后/日报/轮动/策略研究/涨停回马枪等）。
- **特征**：推理更强、更能处理长文档与复杂约束；成本更高但“交付稳定性更关键”。
- **推荐候选**：
  - `kimi-k2-thinking`
  - `kimi-k2.5`
  - `nvidia/llama-3.1-nemotron-70b-instruct`（如稳定可用）

> 实操建议：每档至少准备 **2 个不同 provider 的候选**，用于 403/auth/quota 时快速切换，降低“单点 provider 故障”。

---

## 三、agent → 任务类别 → 推荐档位（基于当前 cron/job 形态的落地建议）

下面映射以你的 cron 任务语义为准（见 `~/.openclaw/cron/jobs.json`），用于指导“默认档位”。

### `etf_data_collector_agent`（数据采集）
- **任务类别**：1) 工具编排 / 数据搬运型
- **默认档位**：**F**
- **建议降级**：F(主) → F(备) → M(兜底)
- **备注**：采集任务应尽量“只做工具调用 + 最小日志”，避免生成长文本浪费 tokens。

### `etf_main`（巡检快报 / 510300 盯盘 / 价格预警轮询）
- **信号+风控巡检快报（强模板）**
  - **任务类别**：2) 结构化巡检快报型
  - **默认档位**：**M**
  - **建议降级**：M(主) → M(备) → S(兜底)
  - **关键点**：强模板任务不要用过弱/过快模型，否则最常见失败是“多输出一行”导致模板违规。
- **510300 日内盯盘监控（阈值触发提醒）**
  - **任务类别**：2)（偏模板/阈值）+ 少量 3) 推理
  - **默认档位**：**M**
  - **建议降级**：M → S
  - **口径更新**：允许同一轮同时产出并发送研究级 call/put 双向信号（在阈值/风控/去重条件通过时），以免只看单一方向漏报。
- **价格预警轮询（跑脚本+发通知）**
  - **任务类别**：1) 或“非 LLM”更优
  - **默认档位**：**F**（或直接不经 LLM，只在需要润色通知文案时才调用）

### `etf_analysis_agent`（盘前/盘后/日报/轮动/策略研究/涨停回马枪）
- **任务类别**：3) 研究报告 / 策略推理型
- **默认档位**：**S**
- **建议降级**：S(主) → S(备) → M(兜底)
- **关键点**：
  - 长报告要避免截断：优先选择上下文更大的模型；
  - 出现“消息投递失败”时通常不是模型问题，优先排查 `message` 通道与限流/权限，而不是盲目升档。

### `ops_agent`（系统健康 / LLM 健康巡检）
- **任务类别**：4) 运维监控 / 日志解析告警型
- **默认档位**：**F**
- **建议降级**：F → F(备) → M（仅用于生成更清晰告警摘要）
- **关键点**：巡检逻辑尽量“解析为主，LLM 为辅”，严格控制输出长度与调用次数。

### `code_maintenance_agent`（代码健康体检）
- **任务类别**：5) 工具链体检总结型
- **默认档位**：**M**
- **建议降级**：M → S（当需要做复杂归因/跨文件修复建议时）

---

## 四、配置落地：你将来应该改哪里

### 1) provider 与可用模型清单
- **位置**：各 agent 的 `agent/models.json`
- **用途**：声明 provider 的 `baseUrl/api/models[]` 等（包含敏感信息时请避免外泄）。
- **建议**：统一在“共享层/模板 agent”维护一份基础 provider，再由各 agent 继承或复制，减少漂移。

---

## 四点五、实施方案（已落地）：方式 A + 方式 B

下面是为了彻底解决“`agents.defaults.model` + 每个 agent 再复制一套 model”导致的维护困难而制定的两步落地方案。

### 方式 A（先做、立刻减负）：删掉与 defaults 重复的 per-agent model

- **目的**：把“需要维护的模型配置面”从 N 份降到 1 份（defaults）+ 少数 override。
- **原则**：
  - 默认属于 **F 档**的 agent：不写 `agents.list[].model`，直接继承 `agents.defaults.model`
  - 只有确实需要 **M / S 档**的 agent：才在 `agents.list[]` 内写 `model` override
- **本机现状（已实施）**：
  - **F（继承 defaults）**：`etf_data_collector_agent`、`etf_notification_agent`、`ops_agent`
  - **M（显式 override）**：`etf_main`、`etf_business_core_agent`、`code_maintenance_agent`
  - **S（显式 override）**：`etf_analysis_agent`

> 备注：你当前可用的模型集合来自 `~/.openclaw/openclaw.json -> models.providers.*`；若你未来增加更强 S 档模型（如 Kimi/K2、Nemotron 70B 等），只需要更新分组配置，不再需要在每个 agent 里重复编辑。

### 方式 B（进一步工程化）：F/M/S 分组文件 → 自动同步到 openclaw.json

OpenClaw 的 `model` 字段本身不支持引用“分组名”（只能写具体 `provider/model` 或 `{primary,fallbacks}`），因此我们采用“**分组文件 + 同步脚本生成**”的方式实现单一事实源（SSOT）。

- **分组文件**：`config/model_routes.json`
  - 定义 F/M/S 三组的 `primary/fallbacks`
  - 定义每个 `agentId` 应绑定的组（F 表示继承 defaults，不写 per-agent model）
- **同步脚本**：`scripts/sync_openclaw_model_routes.py`
  - 读取 `config/model_routes.json`
  - 自动写入 `~/.openclaw/openclaw.json` 的：
    - `agents.defaults.model`（来自 `defaultsGroup` 指定的分组）
    - `agents.list[].model`（仅对非默认分组的 agent 写 override；默认分组则移除 model）
  - 可选环境变量：`PRESERVE_FREERIDE_DEFAULTS=1`
    - **仅当你运行 `freeride auto`，且希望保留它写入的 `agents.defaults.model/models` 时才需要设置**
    - 如果你采用“仅 `freeride list` + 手工编辑 `config/model_routes.json`”的方式，一般**不要**设置该变量，直接同步即可
  - 自动生成备份：`~/.openclaw/openclaw.json.bak.YYYYMMDD_HHMMSS`

#### 关于 `agentDir/agent/models.json`（已统一收敛）

你会在 `~/.openclaw/agents/**/agent/models.json` 看到“每个 agent 自带一份 models/provider 清单”。这通常是为了 **agent 包可独立分发/兼容旧部署** 而存在。

为避免重复维护与密钥泄露，本项目已将这些文件统一收敛为最小占位：

- 内容固定为：
  - `{"providers": {}}`
- 运行时以 `~/.openclaw/openclaw.json` 顶层 `models` 为唯一事实源（SSOT）
- 如果未来确实需要让某个 agent “离线独立运行”，再单独恢复该 agent 的本地 models（不建议日常这样维护）

#### 用法

```bash
python3 ~/.openclaw/workspaces/etf-options-ai-assistant/scripts/sync_openclaw_model_routes.py
```

（可选）只预览不写入：

```bash
DRY_RUN=1 python3 ~/.openclaw/workspaces/etf-options-ai-assistant/scripts/sync_openclaw_model_routes.py
```

---

## 四点六、维护操作（SOP：今后怎么改、怎么生效、怎么回滚）

下面流程只围绕**一个事实源**：`config/model_routes.json`。原则是“只改这一个文件，然后同步”，避免直接手改 `openclaw.json` 造成漂移。

### 1) 调整某个档位（F/M/S）使用的模型

- **改哪里**：`~/.openclaw/workspaces/etf-options-ai-assistant/config/model_routes.json`
- **怎么改**：编辑 `groups.F.model` / `groups.M.model` / `groups.S.model` 的 `primary` 与 `fallbacks`（填写完整的 `provider/model` 字符串）
- **让它生效**：

```bash
python3 ~/.openclaw/workspaces/etf-options-ai-assistant/scripts/sync_openclaw_model_routes.py
```

### 2) 调整某个 agent 绑定到哪个档位（F/M/S）

- **改哪里**：同上文件的 `agents.overrides`
- **怎么改**：
  - 例如把 `etf_analysis_agent` 从 `S` 改成 `M`：修改 `agents.overrides.etf_analysis_agent`
  - 绑定为 **F** 表示“继承 defaults（不写 per-agent model）”
- **让它生效**：同上运行同步脚本

### 3) 新增一个 agent（或新增一个 cron/job 对应的 agentId）

- **步骤**：
  - 在 `openclaw.json -> agents.list` 增加该 `agentId` 与 `agentDir/workspace/tools`（这部分是“agent 注册”，不是模型路由）
  - 在 `config/model_routes.json -> agents.overrides` 里给它指定 `F/M/S`（不写则默认走 `defaultsGroup`）
  - 运行同步脚本

> 提醒：同步脚本只负责写 `agents.defaults.model` 与 `agents.list[].model`，不会改 `tools/agentDir/workspace` 等注册信息。

### 2.5) 仅用 FreeRide `list`：手工挑选 F 档免费候选（不跑 auto）

你当前的做法是：**只运行 `freeride list` 进行免费模型可用性/质量参考**，然后**手动**把“最优的一批免费模型”写入本项目的 `config/model_routes.json -> groups.F.model.primary/fallbacks`。

该模式的好处是：你们的 SSOT 与同步脚本仍然完全掌控 `openclaw.json`（避免 `freeride auto` 与同步脚本互相覆盖）。

#### SOP（建议照抄）
1. 准备：确保 FreeRide 能列出模型（已安装并可运行 `freeride`）
2. 查看免费模型榜单：
   ```bash
   freeride list -n 20
   ```
3. 选定“OpenClaw 能识别/不 missing”的候选：
   ```bash
   openclaw models list
   ```
   原则：优先选择在列表中显示为 `configured`（或至少不带 `missing` 标识）的模型 ID。

   重要提示：FreeRide 返回的 ID 可能是 `openrouter/...:free`，而你的 OpenClaw 当前 provider 前缀可能是 `custom-openrouter-alpha-free/...`；因此最终应以 `openclaw models list` 中“已识别”的模型 ID 为准，避免 fallback 写入后变成 `missing`。

4. 手工更新 SSOT：
   - 编辑 `config/model_routes.json`
   - 把你选中的 OpenClaw 可识别模型 ID 填入：
     - `groups.F.model.primary`
     - `groups.F.model.fallbacks`
5. 同步 + 重启使其生效：
   ```bash
   python3 scripts/sync_openclaw_model_routes.py
   openclaw gateway restart
   ```

### 4) 只想检查、不要落盘（预演）

```bash
DRY_RUN=1 python3 ~/.openclaw/workspaces/etf-options-ai-assistant/scripts/sync_openclaw_model_routes.py
```

### 5) 回滚到同步前的 openclaw.json

每次同步会自动生成备份：`~/.openclaw/openclaw.json.bak.YYYYMMDD_HHMMSS`。

- **回滚做法**：用最近一份备份覆盖回去即可（覆盖前可再备份一次当前文件）。

### 6) 自检：确认“重复配置”没有复活

- **检查点 A（defaults 是否存在）**：`openclaw.json -> agents.defaults.model` 必须存在
- **检查点 B（F 档 agent 不应显式写 model）**：绑定为 F 的 agent，在 `agents.list[]` 中应当**没有** `model` 字段
- **检查点 C（agentDir models 是否为空）**：`~/.openclaw/agents/**/agent/models.json` 固定为 `{"providers": {}}`

---

### 2) agent 的“默认档位”与“候选列表”
建议在每个 agent 的配置层明确：
- **primary**：主模型（按 F/M/S）
- **fallbacks**：同档备选、跨档兜底（按错误类型切换）
- **limits**：maxTokens、超时、最大重试次数

> 由于不同 OpenClaw 版本对“模型选择字段”的 schema 可能不同，推荐做法是：先在你现有的 `agent/models.json` 中选定 **3 个代表模型 id** 作为 F/M/S，然后在 job/workflow 的执行器层用“路由表”去引用它们。

### 3) job / workflow 的“按任务类型选择档位”

建议在你的工作流与任务提示词中显式写出“本任务属于哪一类”，让将来维护的人一眼知道应该用哪档模型。例如：

- `workflows/etf_510300_intraday_monitor.yaml`：类别 2（结构化/阈值触发）→ M
- `workflows/etf_rotation_research.yaml`、`workflows/strategy_research.yaml`：类别 3（研究报告）→ S
- `cron/jobs.json` 中的采集类任务：类别 1 → F
- `shared: LLM 模型健康巡检`：类别 4 → F（只在“写告警摘要”时用 M）

> 落地方式不强求一定写在 YAML/JSON 的哪个字段，而是强调“**配置与文档同步**”：你至少要在 workflow/job 的说明或本方案的映射表中，把该任务归类写清楚。

---

## 五、错误类型驱动的降级策略（推荐统一规范）

不要只做“失败就换模型”，建议按错误类型选择更合理的动作。

### A. 认证/配额/封禁类（403 / auth / quota / All models failed）
- **动作**：优先切换到**不同 provider** 的同档备选（F→F、M→M、S→S）
- **原因**：这类错误通常与模型能力无关，升级档位只会加速消耗/继续失败
- **补充**：`ops_agent` 的 LLM 健康巡检任务可以聚合并告警（你已经在 cron 里定义了这个职责）

### B. 超时/网络波动（timeout / 5xx / connection reset）
- **动作**：同 provider 允许 **一次短重试**（指数退避 1 次即可），仍失败则换到同档备选
- **原因**：短暂网络抖动重试收益高；持续失败再切换 provider

### B-1. OpenRouter free 模型 429 自动切换（冷却绕过修复）
当使用 OpenRouter `:free` 模型时，可能出现 `429 Rate limit exceeded`，但如果 OpenClaw 对 `openrouter` provider **绕过 cooldown**，则“同一 provider 的 profile 仍保持热状态”，进而导致 fallback 链路不触发或触发不稳定。

本项目采用的修复要点是：让 OpenClaw 对 `openrouter` provider 也进入 cooldown。具体实现为在 OpenClaw 打包后的 `dist` 代码中，把 `isAuthCooldownBypassedForProvider(provider)` 改为 **永不 bypass**（返回 `false`），使得 429 后该 provider/profile 进入 cooldown，fallback models 才会按配置自动切换。

验证方式（建议复用到排障）：
- 日志中应先看到 `429 Rate limit exceeded ... free-models-per-day`（或 OpenRouter 的限流提示）
- 随后出现 `model fallback decision` / `failoverReason=rate_limit`，并切到 `nextCandidateModel`（来自当前 agent 的 `fallbacks`）
- 最终应能看到钉钉/飞书投递工具成功返回（如 `tool_send_dingtalk_message` 的 `errcode: 0`）

关于 OpenClaw 升级是否会冲掉：
- 这类修复是直接改动 OpenClaw 打包产物 `dist`（而非仅改 `openclaw.json` 配置）。
- 因此在 `openclaw update` / 重装时，可能被覆盖回原始 `dist` 行为；升级后需要重新对新的 `dist` 应用同样的修改，或重新走“同步/应用到全局 openclaw”的步骤。
- 建议升级后快速自检：确认新版本 `dist` 里 `isAuthCooldownBypassedForProvider` 的实现仍为 `return false;`（即不再对 openrouter bypass cooldown）。

### B-1-1. 升级后重应用操作（你当前用 `openclaw update`）
当你通过 `openclaw update` 升级后，建议执行以下步骤把“openrouter 不绕过 cooldown”的 dist 修复再打一次（全程只改本地 dist 产物，不改你的 `openclaw.json` 路由配置）。

1）确认全局 dist 路径（默认）：
- 全局 OpenClaw：`/home/xie/.npm-global/lib/node_modules/openclaw/dist`

2）让 Cursor 在 `/home/xie/scripts/` 下新增脚本：
- 文件名：`reapply-openclaw-openrouter-cooldown-fix.mjs`
- 脚本用途：扫描 `dist` 里 `isAuthCooldownBypassedForProvider(provider)` 的函数块，并强制把 `return ...;` 替换为 `return false;`

3）执行 apply + verify + 重启（按顺序）：
```bash
node /home/xie/scripts/reapply-openclaw-openrouter-cooldown-fix.mjs "/home/xie/.npm-global/lib/node_modules/openclaw/dist" apply
node /home/xie/scripts/reapply-openclaw-openrouter-cooldown-fix.mjs "/home/xie/.npm-global/lib/node_modules/openclaw/dist" verify
~/scripts/restart-openclaw-services.sh
```

4）验证点（verify 通过后基本就 OK）：
- `verify` 阶段不应报 “VERIFY FAIL”
- 日志里后续出现 `429 ... free-models-per-day` 后，能观察到 fallback/cooldown 相关的切换（如 `model fallback decision`、`failoverReason=rate_limit`）

可直接复制给 Cursor 的提示词（让它生成脚本并跑通）：
```text
在 /home/xie/scripts/ 下新增文件 reapply-openclaw-openrouter-cooldown-fix.mjs，
作用是：遍历传入的 distRoot 下所有 .js 文件，定位函数 isAuthCooldownBypassedForProvider(provider) 的函数块，
把该函数内部第一个 return 语句强制改为 return false;；apply 模式会修改并创建 .bak 备份，verify 模式不修改而是检查是否包含 return false;。
命令依次执行：
1) node /home/xie/scripts/reapply-openclaw-openrouter-cooldown-fix.mjs "/home/xie/.npm-global/lib/node_modules/openclaw/dist" apply
2) node /home/xie/scripts/reapply-openclaw-openrouter-cooldown-fix.mjs "/home/xie/.npm-global/lib/node_modules/openclaw/dist" verify
3) ~/scripts/restart-openclaw-services.sh
把 verify 的输出贴回我。
```

### C. 输出格式违规（模板任务多输出/漏字段/表格错）
- **动作**：优先在同档模型内重试 1 次（强约束模板再强调），仍失败则升一档（M→S）
- **原因**：这类错误与“指令遵循能力”高度相关；升级档位通常有效

### D. 内容质量不足（研究报告浅、逻辑断裂、引用不足）
- **动作**：S 档内换更强候选；必要时增加上下文容量更大的候选
- **原因**：质量问题多数是能力/上下文不足，不是网络问题

---

## 六、推荐的“路由表”模板（你将来新增任务就按此填）

建议维护一张表（可以写在文档里，也可以写成 JSON/YAML 供程序读取）：

| taskKey（自定义） | agentId | 任务类别 | 默认档位 | 主模型 id | 同档备选 id | 跨档兜底 | 备注 |
|---|---|---|---|---|---|---|---|
| collect.minute.high | etf_data_collector_agent | 1 | F | `stepfun/step-3.5-flash:free` | `gemini-2.5-flash` | M:`glm-5` | 高优先级分钟采集 |
| inspect.30m.template | etf_main | 2 | M | `glm-5` | `deepseek-v3.2-chat` | S:`kimi-k2-thinking` | 模板硬约束 |
| report.daily.close | etf_analysis_agent | 3 | S | `kimi-k2-thinking` | `kimi-k2.5` | M:`glm-5` | 长报告 |
| ops.llm_health | ops_agent | 4 | F | `gemini-2.5-flash` | `stepfun/step-3.5-flash:free` | M:`glm-5` | 解析为主，少用 LLM |
| code.health_check | code_maintenance_agent | 5 | M | `glm-5` | `deepseek-v3.2-chat` | S:`kimi-k2-thinking` | 输出建议 diff |

> 表中的模型 id 示例来自你当前的 `models.json`；将来如果你替换/新增 provider，只需要更新“每档 2 个候选 + 兜底 1 个”的组合即可。

---

## 七、任务配置检查清单（上线前 2 分钟自检）

- **任务类别是否明确**：属于 1/2/3/4/5 哪一类？
- **默认档位是否匹配**：模板/巡检类不要用 F；研究长文不要用 F。
- **同档备选是否跨 provider**：至少一个备选来自不同 provider（避免单点故障）。
- **maxTokens 是否合理**：
  - 采集/巡检类：宁可小一些，避免“跑偏写长文”
  - 研究报告类：保证不会被截断（必要时拆分为“分析数据对象 + llm_summary 正文”）
- **投递链路是否与模型无关**：消息发送失败优先排查 `message` 通道/限流/权限。
- **敏感信息是否隔离**：`agent/models.json` 若含 key，避免提交到公开仓库；需要共享时用环境变量或单独私密部署配置。

---

## 八、最小落地建议（不改代码也能立刻用）

如果你暂时不想改任何执行器代码，也可以先做到这三件事，让配置长期可维护：

1. **固定 F/M/S 的“基准模型 id”**（每档 2 个候选 + 1 个兜底）
2. **把每个 cron job / workflow 归类写进文档**（将来新增同类任务直接沿用）
3. **把“错误类型→降级动作”当成统一规范**（减少无效升档与 token 浪费）

---

## 附：当前相关配置位置速查

- `~/.openclaw/cron/jobs.json`：当前定时任务与 `agentId`
- `~/.openclaw/prompts/research.md`：研究模式与各 cron 子流程口径
- `docs/openclaw/*.md`：工作流说明与工具/Token 优化建议
- `workflows/*.yaml`：510300 盯盘、轮动研究、策略研究等工作流定义
