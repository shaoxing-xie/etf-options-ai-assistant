#!/usr/bin/env bash
# 多条 evolution / 波动区间 按需干跑（OpenClaw + etf_main）。
# 用法：
#   ./scripts/evolution_workflows_dry_run.sh research
#   ./scripts/evolution_workflows_dry_run.sh factor
#   ./scripts/evolution_workflows_dry_run.sh strategy
#   ./scripts/evolution_workflows_dry_run.sh volatility      # 干跑：诊断、AUTOFIX_ALLOWED=false
#   ./scripts/evolution_workflows_dry_run.sh volatility-live # 实跑：通过门禁后可改代码并开 PR（见 docs）
#   ./scripts/evolution_workflows_dry_run.sh sync-data       # 将本仓库 data/ 同步到 OpenClaw 工作区
#   ./scripts/evolution_workflows_dry_run.sh all             # 仅串联各子命令的干跑版本
#
# 依赖：已安装 openclaw 且 ~/.openclaw/.env 中可配置 GITHUB_PAT（导出为 GH_TOKEN）。
# 实跑前建议：sync-data；可选 EVO_PAIN_SUMMARY='...' 描述优化目标。
# 建议串行执行（避免同 session 锁）；factor 曾出现 300s LLM 超时，默认 timeout 已调高。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1090
if [[ -f ~/.openclaw/.env ]]; then
  export GH_TOKEN="$(grep '^GITHUB_PAT=' ~/.openclaw/.env | cut -d= -f2- | tail -n 1)"
fi

RUN_ID="${EVO_RUN_ID:-$(date +%Y%m%d-%H%M%S)}"

# 避免模型输出 NO_REPLY 与 ORCH_STATUS 粘连（便于 jq/脚本解析）
EVO_KV_RULES=$'最终输出：仅下列 8 行、每行一条 KEY=value，不要其它说明文字；第一行必须以 ORCH_STATUS= 开头；禁止出现 NO_REPLY 前缀或与 ORCH_STATUS 同一行。'

usage() {
  # 使用变量拼接子命令名，避免编辑器折行在 volatility 处截断引号导致 shell 报错
  local v=volatility
  printf '%s\n' "用法: $0 research | factor | strategy | $v | ${v}-live | sync-data | all" >&2
  printf '%s\n' "可选: EVO_RUN_ID=前缀；OPENCLAW_WORKSPACE=工作区路径；EVO_PAIN_SUMMARY=实跑痛点（${v}-live）" >&2
}

run_research() {
  echo "=== research_checklist_evolution_on_demand (run=${RUN_ID}-research) ==="
  openclaw agent --local \
    --agent etf_main \
    --session-id "${RUN_ID}-research" \
    --thinking off \
    --timeout 300 \
    --verbose on \
    --json \
    --message "使用 workflows/research_checklist_evolution_on_demand.yaml 做一次干跑测试：
- target_doc=docs/research/factor_research_checklist.md
- gap_summary=当前 Checklist 对回测样本期与过拟合风险的要求不够明确，仅建议改文档，不改代码、不创建 PR。

必须按 evolution 系列 Prompt 执行，最终只输出：
ORCH_STATUS
FAILURE_CODES
RISK
AUTOFIX_ALLOWED
PR_CREATED
PR_REF
EVIDENCE_REF
TOP_ACTIONS

${EVO_KV_RULES}"
}

run_factor() {
  echo "=== factor_evolution_on_demand (run=${RUN_ID}-factor) ==="
  openclaw agent --local \
    --agent etf_main \
    --session-id "${RUN_ID}-factor" \
    --thinking off \
    --timeout 600 \
    --verbose on \
    --json \
    --message "使用 workflows/factor_evolution_on_demand.yaml 干跑。
target_factor=factor_momentum_20d
problem_summary=干跑冒烟：验证三 Skill 编排与门禁输出；优先 read config/evolver_scope.yaml 与 plugins/analysis/** 中与因子相关的实现；可少量 grep/短命令，避免长时间回测；不改代码、不创建 PR。
最终只输出键值行：ORCH_STATUS FAILURE_CODES RISK AUTOFIX_ALLOWED PR_CREATED PR_REF EVIDENCE_REF TOP_ACTIONS

${EVO_KV_RULES}"
}

run_strategy() {
  echo "=== strategy_param_evolution_on_demand (run=${RUN_ID}-strategy) ==="
  openclaw agent --local \
    --agent etf_main \
    --session-id "${RUN_ID}-strategy" \
    --thinking off \
    --timeout 600 \
    --verbose on \
    --json \
    --message "使用 workflows/strategy_param_evolution_on_demand.yaml 干跑。
target_strategy=trend_following_510300
performance_issue=干跑冒烟：验证编排与键值输出；read config/evolver_scope.yaml，并在 allowed_paths 内定位策略相关配置（read/grep），禁止长时间回测；不改代码、不创建 PR。
最终只输出键值行：ORCH_STATUS FAILURE_CODES RISK AUTOFIX_ALLOWED PR_CREATED PR_REF EVIDENCE_REF TOP_ACTIONS

${EVO_KV_RULES}"
}

run_volatility() {
  echo "=== volatility_range_evolution_on_demand (run=${RUN_ID}-volatility) ==="
  openclaw agent --local \
    --agent etf_main \
    --session-id "${RUN_ID}-volatility" \
    --thinking off \
    --timeout 900 \
    --verbose on \
    --json \
    --message "使用 workflows/volatility_range_evolution_on_demand.yaml 干跑（仅诊断，默认不建 PR）。

target_symbols=510300
evaluation_window=30
pain_summary=干跑冒烟：验证三 Skill + 真实取证；AUTOFIX_ALLOWED=false。

说明（必读）：data/ 在 .gitignore 中，OpenClaw 的 workspaceDir 常为 ~/.openclaw/workspaces/etf-options-ai-assistant，未必含本机克隆里已生成的 data。exec 时先 pwd，再 ls data/prediction_records data/volatility_ranges；若为空，TOP_ACTIONS 须提示用户执行 rsync：rsync -a ~/etf-options-ai-assistant/data/ <workspaceDir>/data/（或仅在两子目录间同步），禁止谎称「本机无数据」。

硬性门禁（违反任一条则必须 ORCH_STATUS=TEAM_FAIL，不得使用 FAILURE_CODES=NONE）：
1) exec：pwd；ls -la data/prediction_records data/volatility_ranges 2>&1；输出须来自工具回显，禁止凭记忆写 none。
2) read config/evolver_scope.yaml。
3) 若上一步 ls 显示无 predictions_*.json 或无 volatility_ranges/*.json：输出 TEAM_FAIL + FAILURE_CODES=NO_LOCAL_PREDICTION_ARTIFACTS，TOP_ACTIONS=先跑盘前/日内/信号工作流使 tool_predict_* 落库后再重跑本任务；禁止编造「新建模块/手建目录」类建议。
4) 若存在 json：read 至少一个具体文件路径（写明路径）。
5) 必须实际调用 tavily_search；EVIDENCE_REF 中须出现字面量 https://（来自检索结果原文），否则 TEAM_FAIL + FAILURE_CODES=NO_EVIDENCE。

再输出 8 行键值：ORCH_STATUS FAILURE_CODES RISK AUTOFIX_ALLOWED PR_CREATED PR_REF EVIDENCE_REF TOP_ACTIONS

${EVO_KV_RULES}"
}

run_volatility_live() {
  local pain="${EVO_PAIN_SUMMARY:-宽基 510300 预测波动区间需结合近窗实现波动与 prediction_records / volatility_ranges 做校准；在证据充分时做最小改动（config 或 analysis/src 允许路径内）}"
  # 防止 pain 中有双引号打断后续 shell/openclaw 参数解析
  pain="${pain//\"/}"

  echo "=== volatility_range_evolution_on_demand 实跑 (run=${RUN_ID}-volatility-live) ==="

  local msg
  # 使用 heredoc 避免 --message 多行双引号在编辑器折行/特殊符号下提前闭合
  msg="$(cat <<EOF
使用 workflows/volatility_range_evolution_on_demand.yaml 进行实跑（非干跑，非仅诊断）。

target_symbols=510300
evaluation_window=30
pain_summary=${pain}

runbook：先 read config/evolver_scope.yaml 与 docs/openclaw/execution_contract.md；按 orchestrator_evolution 顺序 Builder 取证 → Reviewer 复核 →（条件满足）实施最小修改 → Evolver 复盘。

证据门禁（与干跑相同，缺一不可）：
1) exec：pwd；ls -la data/prediction_records data/volatility_ranges 2>&1
2) 若工作区无 json：先 TEAM_FAIL，TOP_ACTIONS=运行本仓库 ./scripts/evolution_workflows_dry_run.sh sync-data 后重试
3) read 至少一个 predictions_*.json 与一个 volatility_ranges/*.json（或合理解释缺失）
4) tavily_search 一次；EVIDENCE_REF 须含 https://

实跑 PR 规则（须同时满足才可 PR_CREATED 为 true）：
- Reviewer 判定 TEAM_OK、RISK=LOW、AUTOFIX_ALLOWED=true
- 变更路径均在 allowed_paths，且不触 denied_paths
- 仅在分支前缀 ai-evolve/analysis-* 上创建 PR（建议 ai-evolve/analysis-volatility-主题词），禁止直接改 main，禁止自动 merge

若证据不足或风险偏高：AUTOFIX_ALLOWED=false，PR_CREATED=false，只输出诊断与 TOP_ACTIONS。

最终只输出 8 行键值：ORCH_STATUS FAILURE_CODES RISK AUTOFIX_ALLOWED PR_CREATED PR_REF EVIDENCE_REF TOP_ACTIONS

${EVO_KV_RULES}
EOF
)"

  openclaw agent --local \
    --agent etf_main \
    --session-id "${RUN_ID}-volatility-live" \
    --thinking off \
    --timeout 1200 \
    --verbose on \
    --json \
    --message "$msg"
}

case "${1:-}" in
  research) run_research ;;
  factor) run_factor ;;
  strategy) run_strategy ;;
  volatility) run_volatility ;;
  'volatility-live') run_volatility_live ;;
  all)
    run_research
    echo ""
    run_factor
    echo ""
    run_strategy
    echo ""
    run_volatility
    ;;
  sync-data)
    WS="${OPENCLAW_WORKSPACE:-$HOME/.openclaw/workspaces/etf-options-ai-assistant}"
    mkdir -p "$WS/data/prediction_records" "$WS/data/volatility_ranges"
    rsync -a "$ROOT/data/prediction_records/" "$WS/data/prediction_records/"
    rsync -a "$ROOT/data/volatility_ranges/" "$WS/data/volatility_ranges/"
    printf '已同步 data 至 OpenClaw 工作区: %s\n' "$WS"
    ls -la "$WS/data/prediction_records" | tail -n 5
    ls -la "$WS/data/volatility_ranges" | tail -n 5
    ;;
  *)
    usage
    exit 1
    ;;
esac
