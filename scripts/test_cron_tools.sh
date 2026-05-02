#!/usr/bin/env bash
# ============================================================
# 常用测试场景示例（可直接复制执行）
#
# 1) 只对“单个任务”做工具冒烟（默认不跑 cron、不发真实通知）
#    - 适合：验证 payload.message 里引用的 tool_* 是否可用/参数是否兼容
#    - 说明：tools 模式会从 payload.message 抽取 tool_* 并用 tool_runner.py 冒烟（默认跳过 tool_send_*）
#
#    # 仅测宽基ETF早盘
#    scripts/test_cron_tools.sh --filter "^etf-signal-risk-inspection-morning$"
#
#    # 仅测宽基ETF午间
#    scripts/test_cron_tools.sh --filter "^etf-signal-risk-inspection-midday$"
#
#    # 仅测宽基ETF三档（早盘/午间/下午）
#    scripts/test_cron_tools.sh --filter "^etf-signal-risk-inspection-(morning|midday|afternoon)$"
#
#    说明：Cron 推荐 payload 仅触发单次 tool_run_signal_risk_inspection_and_send；tools 冒烟可对应该工具：
#    python3 tool_runner.py tool_run_signal_risk_inspection_and_send phase=midday mode=test fetch_mode=test
#
#    9:28 开盘行情分析（job id f0d82a29-…）推荐单次 tool_run_opening_analysis_and_send；tools 冒烟示例：
#    python3 tool_runner.py tool_run_opening_analysis_and_send mode=test fetch_mode=test
#
# 2) 对“单个任务”做端到端 cron 真跑（会真实调模型/工具，可能触发真实投递）
#    - 适合：验证 openclaw cron run + runs/*.jsonl 落地 +（可选）投递证据
#
#    # 真跑 + 等待 runs 里 finished 落盘（推荐）
#    scripts/test_cron_tools.sh --mode cron --filter "^etf-signal-risk-inspection-morning$" --wait-finished
#
#    # 真跑 + 等待 finished + 校验 tool_send_* 的 toolResult（谨慎：可能真实发送）
#    scripts/test_cron_tools.sh --mode cron --filter "^etf-signal-risk-inspection-morning$" --wait-finished --verify-send --expect-final --include-send
#
# 3) 批量回归（只跑你关心的一组任务）
#    - 适合：日常回归某一类任务（例如所有“巡检/快报”）
#
#    # 工具冒烟批量回归（安全）
#    scripts/test_cron_tools.sh --filter "巡检|快报|inspection|health"
#
#    # cron 真跑批量回归（高成本/高风险：可能真实发送）
#    scripts/test_cron_tools.sh --mode cron --wait-finished --filter "etf-signal-risk-inspection|ops-health|llm-health"
#
# 4) 指定 jobs.json（当你在不同环境/分支下测试）
#
#    JOBS_JSON="$HOME/.openclaw/cron/jobs.json" scripts/test_cron_tools.sh --filter "^ops-health-merged-"
#    scripts/test_cron_tools.sh --jobs "$HOME/.openclaw/cron/jobs.json" --filter "^etf-"
#
# 5) 调整等待/轮询（排查“runningAtMs 已有但 finished 没落盘”等情况）
#
#    scripts/test_cron_tools.sh --mode cron --filter "^etf-signal-risk-inspection-midday$" --wait-finished \
#      --wait-timeout-seconds 1800 --poll-seconds 2
#
# ============================================================
# 批量测试 ~/.openclaw/cron/jobs.json 中各定时任务涉及的工具
# - tools 模式：从 payload.message 抽取 tool_*，用 tool_runner.py 冒烟（默认跳过 tool_send_*）
# - cron 模式：openclaw cron run（真实执行）；建议配合 --wait-finished --verify-send 做端到端校验
#
# 发送校验（--verify-send）逻辑（与 delivery.mode=none 一致）：
# - 以会话 *.jsonl 中 tool_send_* 的 toolResult 为权威：至少一次 success（钉钉 errcode 0 等）
# - runs.jsonl 的 delivered / deliveryStatus：mode=none 时常为假阴性；--wait-finished 打印的 FINISHED 行会合并
#   finished.summary 里 ACK JSON 的 delivery_success=true，避免“钉钉已收到仍显示未投递”
# - 会话路径：~/.openclaw/agents/<job.agentId>/sessions/<sessionId>.jsonl

# 不 set -e，跑完全部用例并汇总
cd "$(dirname "$0")/.."
PY_BIN="./.venv/bin/python"
RUNNER="./.venv/bin/python tool_runner.py"

JOBS_JSON="${JOBS_JSON:-$HOME/.openclaw/cron/jobs.json}"
OUT_DIR="./test_cron_results"
FILTER_REGEX=""
INCLUDE_DISABLED="0"
INCLUDE_SEND="0"
MODE="tools" # tools | cron
CRON_TIMEOUT_MS="1800000"
EXPECT_FINAL="0"
WAIT_FINISHED="0"
VERIFY_SEND="0"
# 默认等待 finished；若某任务 payload.timeoutSeconds 更大，run_job_cron 会自动延长（+120s 缓冲）
WAIT_TIMEOUT_SECONDS="900"
POLL_SECONDS="5"
SEND_OK=0
SEND_FAIL=0
SEND_UNKNOWN=0
HARD_FAIL_ON_MISSING_SEND="1"
PREFLIGHT_CHECK="${PREFLIGHT_CHECK:-1}"
MANUAL_ORCH_SESSION_TYPE="${MANUAL_ORCH_SESSION_TYPE:-manual}"

usage() {
  cat <<'EOF'
用法:
  scripts/test_cron_tools.sh [options]

选项:
  --jobs <path>              jobs.json 路径（默认: ~/.openclaw/cron/jobs.json）
  --out <dir>                输出目录（默认: ./test_cron_results）
  --filter <regex>           仅测试 id 或 name 匹配的任务（Python 正则）
  --include-disabled         包含 enabled=false 的任务
  --include-send             也测试 tool_send_*（可能触发真实通知，谨慎）
  --mode <tools|cron>        tools: 用 tool_runner 冒烟工具；cron: openclaw cron run（可能触发真实投递/通知，谨慎）
  --cron-timeout-ms <ms>     cron 模式 timeout（默认: 1800000）
  --expect-final             cron 模式等待 agent 最终回复
  --wait-finished            cron 模式轮询 runs/*.jsonl，等待本次 run 落地 finished（推荐）
  --verify-send              需同时加 --wait-finished：按会话 tool_send_* 的 toolResult 校验是否真正投递成功
  --wait-timeout-seconds <n> 等待 finished 的基础超时秒数（默认: 900）；若 jobs.json 中该任务 payload.timeoutSeconds 更大，则实际等待为 max(n, timeoutSeconds+120)
  --poll-seconds <n>         轮询间隔秒数（默认: 5）
  --no-hard-fail-send        关闭“应发送但无证据即失败”的硬失败（默认开启）

环境变量:
  JOBS_JSON=<path>           等价于 --jobs
  MANUAL_ORCH_SESSION_TYPE   cron 手工触发时注入的 ORCH_SESSION_TYPE（默认: manual）

示例:
  # 工具冒烟（不发真实通知）
  scripts/test_cron_tools.sh --filter "盘后|after_close"
  scripts/test_cron_tools.sh --include-disabled
  # 批量 cron 真跑 + 等 finished + 校验发送（会真实调模型与通知，慎用）
  scripts/test_cron_tools.sh --mode cron --wait-finished --verify-send --expect-final
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --jobs) JOBS_JSON="$2"; shift 2 ;;
    --out) OUT_DIR="$2"; shift 2 ;;
    --filter) FILTER_REGEX="$2"; shift 2 ;;
    --include-disabled) INCLUDE_DISABLED="1"; shift ;;
    --include-send) INCLUDE_SEND="1"; shift ;;
    --mode) MODE="$2"; shift 2 ;;
    --cron-timeout-ms) CRON_TIMEOUT_MS="$2"; shift 2 ;;
    --expect-final) EXPECT_FINAL="1"; shift ;;
    --wait-finished) WAIT_FINISHED="1"; shift ;;
    --verify-send) VERIFY_SEND="1"; shift ;;
    --wait-timeout-seconds) WAIT_TIMEOUT_SECONDS="$2"; shift 2 ;;
    --poll-seconds) POLL_SECONDS="$2"; shift 2 ;;
    --no-hard-fail-send) HARD_FAIL_ON_MISSING_SEND="0"; shift ;;
    --no-preflight) PREFLIGHT_CHECK="0"; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "未知参数: $1"
      usage
      exit 2
      ;;
  esac
done

if [[ "${PREFLIGHT_CHECK:-1}" == "1" ]]; then
  if ! bash scripts/verify_openclaw_config.sh >/dev/null; then
    echo "[test_cron_tools] preflight failed: scripts/verify_openclaw_config.sh" >&2
    echo "[test_cron_tools] hint: set PREFLIGHT_CHECK=0 or pass --no-preflight to bypass (not recommended)" >&2
    exit 1
  fi
fi

mkdir -p "$OUT_DIR"
LOG="$OUT_DIR/run_$(date +%Y%m%d_%H%M%S).log"

PASS=0
FAIL=0
SKIP=0
JOB_PASS=0
JOB_FAIL=0
JOB_SKIP=0

echo "jobs.json: $JOBS_JSON" | tee "$LOG"
echo "模式: $MODE (include_send=$INCLUDE_SEND include_disabled=$INCLUDE_DISABLED filter=${FILTER_REGEX:-<none>})" | tee -a "$LOG"
echo "cron: expect_final=$EXPECT_FINAL wait_finished=$WAIT_FINISHED verify_send=$VERIFY_SEND hard_fail_send=$HARD_FAIL_ON_MISSING_SEND wait_timeout=${WAIT_TIMEOUT_SECONDS}s poll=${POLL_SECONDS}s" | tee -a "$LOG"
if [[ "$VERIFY_SEND" == "1" && "$WAIT_FINISHED" != "1" ]]; then
  echo "WARNING: 已启用 --verify-send 但未启用 --wait-finished，将无法等待 finished 记录，发送校验不会执行。请使用: --wait-finished --verify-send" | tee -a "$LOG"
fi
echo "结果目录: $OUT_DIR" | tee -a "$LOG"
echo "日志: $LOG" | tee -a "$LOG"
echo "" | tee -a "$LOG"

run_tool() {
  local name="$1"
  local tool="$2"
  local args="$3"
  echo -n "--- $name ($tool) ... " | tee -a "$LOG"
  if out=$($RUNNER "$tool" "$args" 2>&1); then
    echo "OK" | tee -a "$LOG"
    echo "$out" | head -c 400 >> "$LOG"
    echo "" >> "$LOG"
    ((PASS++)) || true
    return 0
  else
    echo "FAIL" | tee -a "$LOG"
    echo "$out" | head -c 600 >> "$LOG"
    echo "" >> "$LOG"
    ((FAIL++)) || true
    return 1
  fi
}

default_args_for_tool() {
  local tool="$1"
  local today
  today="$(date +%Y%m%d)"
  case "$tool" in
    # 分析
    tool_analyze_before_open) echo '{}' ;;
    tool_analyze_opening_market) echo '{}' ;;
    tool_analyze_after_close) echo '{}' ;;
    tool_predict_intraday_range) echo '{"symbol":"510300"}' ;;
    tool_predict_daily_volatility_range) echo '{"underlying":"510300"}' ;;
    tool_generate_signals) echo '{"underlying":"510300","mode":"test"}' ;;
    tool_generate_option_trading_signals) echo '{"underlying":"510300","mode":"test"}' ;;
    tool_generate_etf_trading_signals) echo '{"etf_symbol":"510300","mode":"test"}' ;;
    tool_generate_stock_trading_signals) echo '{"symbol":"600519","mode":"test"}' ;;
    tool_assess_risk) echo '{"symbol":"510300"}' ;;
    tool_calculate_historical_volatility) echo '{"symbol":"510300","data_type":"etf_daily","lookback_days":60}' ;;
    tool_underlying_historical_snapshot|tool_historical_snapshot) echo '{"symbols":"510300","max_symbols":1}' ;;
    tool_predict_volatility) echo '{"underlying":"510300"}' ;;
    tool_calculate_technical_indicators) echo '{"symbol":"510300","data_type":"etf_minute"}' ;;
    tool_check_etf_index_consistency) echo '{"etf_symbol":"510300","index_code":"000300"}' ;;
    tool_generate_trend_following_signal) echo '{"etf_symbol":"510300","index_code":"000300"}' ;;
    tool_check_stop_loss_take_profit) echo '{"action":"check","symbol":"510300"}' ;;
    tool_record_signal_effect) echo "{\"signal_id\":\"TEST_${today}\",\"signal_type\":\"buy\",\"etf_symbol\":\"510300\",\"signal_strength\":0.6,\"strategy\":\"trend_following\",\"entry_price\":4.0,\"status\":\"pending\"}" ;;
    tool_screen_equity_factors) echo '{"universe":"custom","custom_symbols":"600000","top_n":3,"max_universe_size":3,"factors":["reversal_5d"]}' ;;
    tool_finalize_screening_nightly) echo '{"screening_result":{"success":true,"data":[{"symbol":"600000","score":0.5,"factors":{}}],"quality_score":0.9,"degraded":false,"config_hash":"test","elapsed_ms":1,"plugin_version":"test"}}' ;;
    tool_set_screening_emergency_pause) echo '{"active":false,"reason":"test"}' ;;

    # 数据采集
    tool_fetch_index_opening) echo '{"index_code":"000300","mode":"test"}' ;;
    tool_fetch_index_realtime) echo '{"index_code":"000300","mode":"test"}' ;;
    tool_fetch_index_historical) echo '{"index_code":"000300","lookback_days":5}' ;;
    tool_fetch_index_minute) echo '{"index_code":"000300","period":"5,15,30","lookback_days":5,"mode":"test"}' ;;
    tool_fetch_global_index_spot) echo '{}' ;;
    tool_fetch_etf_realtime) echo '{"etf_code":"510300"}' ;;
    tool_fetch_etf_data) echo '{"data_type":"realtime","etf_code":"510300"}' ;;

    tool_fetch_etf_realtime) echo '{"etf_code":"510300,510050,510500","mode":"test"}' ;;
    tool_fetch_etf_historical) echo '{"etf_code":"510300","lookback_days":5}' ;;
    tool_fetch_etf_minute) echo '{"etf_code":"510300","period":"5,15,30","lookback_days":5,"mode":"test"}' ;;

    tool_fetch_option_greeks) echo '{"contract_code":"10010466","mode":"test"}' ;;

    # 涨停回马枪
    tool_dragon_tiger_list) echo "{\"date\":\"${today}\"}" ;;
    tool_limit_up_daily_flow) echo '{"write_json":true,"write_report":true,"send_feishu":false}' ;;
    tool_capital_flow) echo '{"symbols":"600000,000001,300750","lookback_days":3}' ;;
    tool_fetch_policy_news) echo '{"disable_network":true}' ;;
    tool_fetch_macro_commodities) echo '{"disable_network":true}' ;;
    tool_fetch_overnight_futures_digest) echo '{"disable_network":true}' ;;
    tool_conditional_overnight_futures_digest) echo '{"overnight_overlay_degraded":true,"disable_network":true}' ;;
    tool_fetch_announcement_digest) echo '{"disable_network":true}' ;;
    tool_compute_index_key_levels) echo '{"index_code":"000300"}' ;;
    tool_record_before_open_prediction) echo '{"report_data":{"report_type":"before_open"}}' ;;
    tool_get_yesterday_prediction_review) echo '{}' ;;

    # 通知类：默认会跳过（除非 --include-send）
    tool_send_daily_report) echo '{"message":"[TEST] skip sending by default"}' ;;
    tool_send_signal_alert) echo '{"signal_data":[]}' ;;
    tool_send_risk_alert) echo '{"risk_data":{}}' ;;

    *) echo '{}' ;;
  esac
}

run_job_tools() {
  local job_id="$1"
  local job_name="$2"
  local enabled="$3"
  local tools_csv="$4"

  local job_ok="1"
  echo "=== JOB $job_id ===" | tee -a "$LOG"
  echo "name: $job_name" | tee -a "$LOG"
  echo "enabled: $enabled" | tee -a "$LOG"
  echo "tools: ${tools_csv:-<none>}" | tee -a "$LOG"

  if [[ "$enabled" != "true" && "$INCLUDE_DISABLED" != "1" ]]; then
    echo "SKIP: disabled (use --include-disabled to include)" | tee -a "$LOG"
    ((JOB_SKIP++)) || true
    ((SKIP++)) || true
    echo "" | tee -a "$LOG"
    return 0
  fi

  if [[ -z "$tools_csv" ]]; then
    echo "SKIP: no tool_* found in payload.message" | tee -a "$LOG"
    ((JOB_SKIP++)) || true
    ((SKIP++)) || true
    echo "" | tee -a "$LOG"
    return 0
  fi

  IFS=',' read -r -a tools <<<"$tools_csv"
  for tool in "${tools[@]}"; do
    tool="$(echo "$tool" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [[ -z "$tool" ]] && continue

    if [[ "$INCLUDE_SEND" != "1" && "$tool" == tool_send_* ]]; then
      echo "--- $job_name ($tool) ... SKIP (tool_send_*; use --include-send)" | tee -a "$LOG"
      ((SKIP++)) || true
      continue
    fi

    if [[ "$tool" == "tool_run_510300_monitor" ]]; then
      echo "--- $job_name ($tool) ... SKIP (not available in tool_runner.py)" | tee -a "$LOG"
      ((SKIP++)) || true
      continue
    fi

    local args
    args="$(default_args_for_tool "$tool")"
    if ! run_tool "$job_name" "$tool" "$args"; then
      job_ok="0"
    fi
  done

  if [[ "$job_ok" == "1" ]]; then
    ((JOB_PASS++)) || true
  else
    ((JOB_FAIL++)) || true
  fi
  echo "" | tee -a "$LOG"
  return 0
}

run_job_cron() {
  local job_id="$1"
  local job_name="$2"
  local enabled="$3"
  local tools_csv="$4"
  local agent_id="${5:-}"
  # 来自 jobs.json payload.timeoutSeconds（秒），用于延长 --wait-finished 上限
  local job_timeout_sec="${6:-}"
  local payload_message="${7:-}"

  echo "=== JOB $job_id (cron run) ===" | tee -a "$LOG"
  echo "name: $job_name" | tee -a "$LOG"
  echo "enabled: $enabled" | tee -a "$LOG"
  echo "agentId: ${agent_id:-<none>}" | tee -a "$LOG"
  echo "tools: ${tools_csv:-<none>}" | tee -a "$LOG"

  if [[ "$enabled" != "true" && "$INCLUDE_DISABLED" != "1" ]]; then
    echo "SKIP: disabled (use --include-disabled to include)" | tee -a "$LOG"
    ((JOB_SKIP++)) || true
    ((SKIP++)) || true
    echo "" | tee -a "$LOG"
    return 0
  fi

  # 注意：cron run 会按任务真实 payload 执行，可能触发真实外部通知/投递
  # openclaw cron run --timeout 默认 30min 时，若 jobs.json 的 timeoutSeconds 更大（如轮动研究 45–60min），
  # 会导致 CLI 侧先超时或 finished 记录为 job execution timed out；此处与 payload 对齐并留缓冲。
  local effective_cron_ms="$CRON_TIMEOUT_MS"
  if [[ -n "$job_timeout_sec" && "$job_timeout_sec" =~ ^[0-9]+$ ]]; then
    local need_ms=$(( (job_timeout_sec + 180) * 1000 ))
    if [[ "$need_ms" -gt "$effective_cron_ms" ]]; then
      effective_cron_ms="$need_ms"
      echo "INFO: cron run --timeout bumped to ${effective_cron_ms}ms (job payload.timeoutSeconds=${job_timeout_sec}s)" | tee -a "$LOG"
    fi
  fi
  # 手工脚本触发（scripts/test_cron_tools.sh）需要“强制启动执行”，即使同一窗口已经 already_executed。
  # 约定：当 filter 形态是精确 job_id（^<id>$）且该任务走 orchestration_entrypoint 时，注入 ORCH_SESSION_TYPE=manual
  # 从而使其 idempotency_key 带 session_type 后缀，不被 cron 口径的 already_executed 拦住。
  if [[ -n "$payload_message" && "$payload_message" == *"scripts/orchestration_entrypoint.py"* ]]; then
    if [[ "$FILTER_REGEX" == "^${job_id}$" ]]; then
      export ORCH_SESSION_TYPE="$MANUAL_ORCH_SESSION_TYPE"
      echo "INFO: manual cron trigger detected (filter=^${job_id}$); set ORCH_SESSION_TYPE=$ORCH_SESSION_TYPE" | tee -a "$LOG"
    else
      unset ORCH_SESSION_TYPE || true
    fi
  fi

  local cmd=(openclaw cron run "$job_id" --timeout "$effective_cron_ms")
  if [[ "$EXPECT_FINAL" == "1" ]]; then
    cmd+=(--expect-final)
  fi
  local run_start_ms
  run_start_ms="$("$PY_BIN" - <<'PY'
import time
print(int(time.time()*1000))
PY
)"
  echo -n "--- $job_name (openclaw cron run) ... " | tee -a "$LOG"
  if out=$("${cmd[@]}" 2>&1); then
    echo "OK" | tee -a "$LOG"
    echo "$out" | head -c 1200 >> "$LOG"
    echo "" >> "$LOG"
    # cron run 可能返回 0 但语义为 ran=false/already-running
    if echo "$out" | grep -Eq '"reason"[[:space:]]*:[[:space:]]*"already-running"|already-running|"ran"[[:space:]]*:[[:space:]]*false'; then
      ((JOB_SKIP++)) || true
      ((SKIP++)) || true
      echo "INFO: already-running -> SKIP" | tee -a "$LOG"
    else
      ((JOB_PASS++)) || true
    fi
  else
    # 网关偶发 1006 断连：重试一次，避免把基础设施抖动判为业务失败
    if echo "$out" | grep -Eq 'gateway closed|1006 abnormal closure|abnormal closure'; then
      echo "RETRY(1): gateway disconnected, retrying once..." | tee -a "$LOG"
      sleep 2
      if out=$("${cmd[@]}" 2>&1); then
        echo "OK(after retry)" | tee -a "$LOG"
        echo "$out" | head -c 1200 >> "$LOG"
        echo "" >> "$LOG"
        if echo "$out" | grep -Eq '"reason"[[:space:]]*:[[:space:]]*"already-running"|already-running|"ran"[[:space:]]*:[[:space:]]*false'; then
          ((JOB_SKIP++)) || true
          ((SKIP++)) || true
          echo "INFO: already-running -> SKIP" | tee -a "$LOG"
        else
          ((JOB_PASS++)) || true
        fi
      else
        echo "FAIL" | tee -a "$LOG"
        echo "$out" | head -c 1600 >> "$LOG"
        echo "" >> "$LOG"
        ((JOB_FAIL++)) || true
      fi
    else
      echo "FAIL" | tee -a "$LOG"
      echo "$out" | head -c 1600 >> "$LOG"
      echo "" >> "$LOG"
      ((JOB_FAIL++)) || true
      # already-running 视为跳过，不算真实失败
      if echo "$out" | grep -Eq '"reason"[[:space:]]*:[[:space:]]*"already-running"'; then
        ((JOB_SKIP++)) || true
        ((JOB_FAIL--)) || true
        ((SKIP++)) || true
        echo "INFO: already-running -> SKIP" | tee -a "$LOG"
      fi
    fi
  fi

  if [[ "$WAIT_FINISHED" == "1" ]]; then
    local runs_file="$HOME/.openclaw/cron/runs/${job_id}.jsonl"
    local eff_wait="$WAIT_TIMEOUT_SECONDS"
    if [[ -n "$job_timeout_sec" && "$job_timeout_sec" =~ ^[0-9]+$ ]]; then
      local padded=$(( job_timeout_sec + 120 ))
      if (( padded > eff_wait )); then
        eff_wait=$padded
      fi
    fi
    if (( eff_wait != WAIT_TIMEOUT_SECONDS )); then
      echo "WAIT: using ${eff_wait}s for finished (base ${WAIT_TIMEOUT_SECONDS}s, job timeoutSeconds=${job_timeout_sec})" | tee -a "$LOG"
    fi
    local wait_deadline=$(( $(date +%s) + eff_wait ))
    local found_json=""
    while [[ $(date +%s) -lt $wait_deadline ]]; do
      if [[ -f "$runs_file" ]]; then
        found_json="$("$PY_BIN" - <<'PY' "$runs_file" "$run_start_ms"
import json, sys
path = sys.argv[1]
start_ms = int(sys.argv[2])
last = None
with open(path, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("action") != "finished":
            continue
        run_at = int(obj.get("runAtMs", 0) or 0)
        if run_at < start_ms:
            continue
        if last is None or run_at >= int(last.get("runAtMs", 0) or 0):
            last = obj
if last is None:
    print("")
else:
    print(json.dumps(last, ensure_ascii=False))
PY
)"
      fi
      if [[ -n "$found_json" ]]; then
        break
      fi
      sleep "$POLL_SECONDS"
    done

    if [[ -z "$found_json" ]]; then
      echo "WAIT: no finished record within ${eff_wait}s (base_wait=${WAIT_TIMEOUT_SECONDS}s job_timeoutSeconds=${job_timeout_sec:-—})" | tee -a "$LOG"
    else
      local finished_status delivered delivery_status finished_error
      local session_id session_key summary_present
      # OpenClaw runs.jsonl：delivery.mode=none 时框架几乎恒为 delivered=false（见 docs/openclaw/cron_delivery_delivered_field.md）。
      # 复合发送工具的真实结果体现在 summary ACK 的 delivery_success 或会话 toolResult；此处合并显示避免假阴性。
      local _fd_lines
      mapfile -t _fd_lines < <("$PY_BIN" - <<'PY' "$found_json"
import json, re, sys

def ack_delivery_success(summary: str) -> bool:
    if not (summary or "").strip():
        return False
    s = summary.strip()
    try:
        obj = json.loads(s)
        if isinstance(obj, dict) and obj.get("delivery_success") is True:
            return True
    except Exception:
        pass
    return bool(re.search(r'"delivery_success"\s*:\s*true', s))

o = json.loads(sys.argv[1])
finished_status = o.get("status")
finished_error = o.get("error")
fw_delivered = o.get("delivered")
fw_ds = (o.get("deliveryStatus") or "") or ""
summary = o.get("summary") or ""
ack_ok = ack_delivery_success(summary)

if fw_delivered is True:
    delivered_out = True
    ds_out = fw_ds or "delivered"
elif ack_ok:
    delivered_out = True
    ds_out = "tool-ack-ok"
else:
    delivered_out = bool(fw_delivered)
    ds_out = fw_ds or "not-delivered"

print(finished_status or "")
print(delivered_out)
print(ds_out or "")
print("" if finished_error is None else str(finished_error))
PY
)
      finished_status="${_fd_lines[0]:-}"
      delivered="${_fd_lines[1]:-}"
      delivery_status="${_fd_lines[2]:-}"
      finished_error="${_fd_lines[3]:-}"
      session_id="$("$PY_BIN" - <<'PY' "$found_json"
import json,sys
o=json.loads(sys.argv[1]); print(o.get("sessionId"))
PY
)"
      session_key="$("$PY_BIN" - <<'PY' "$found_json"
import json,sys
o=json.loads(sys.argv[1]); print(o.get("sessionKey"))
PY
)"
      summary_present="$("$PY_BIN" - <<'PY' "$found_json"
import json,sys
o=json.loads(sys.argv[1]); s=o.get("summary")
print("1" if isinstance(s,str) and s.strip() else "0")
PY
)"
      echo "FINISHED: status=$finished_status delivered=$delivered deliveryStatus=$delivery_status error=$finished_error" | tee -a "$LOG"
      echo "TRACE: sessionId=$session_id sessionKey=$session_key summary_present=$summary_present" | tee -a "$LOG"

      # 对声明了工具的任务：summary 为空时先检查 session 中是否有真实 toolCall/toolResult 证据。
      # 若存在证据则不判失败（避免误杀：模型已发起工具但 summary 未写入）；否则硬失败。
      if [[ -n "$tools_csv" && "$summary_present" == "0" ]]; then
        local ev_out
        ev_out="$("$PY_BIN" - <<'PY' "$HOME" "${agent_id:-}" "${session_id:-}" "${tools_csv:-}"
import glob, json, os, sys
home = sys.argv[1]
agent_id = (sys.argv[2] or "").strip()
session_id = (sys.argv[3] or "").strip()
tools_csv = (sys.argv[4] or "").strip()

if not session_id:
    print("FAIL\tno_session_id")
    raise SystemExit(0)

session_file = os.path.join(home, ".openclaw", "agents", agent_id, "sessions", session_id + ".jsonl")
if not os.path.isfile(session_file):
    pat = os.path.join(home, ".openclaw", "agents", "*", "sessions", session_id + ".jsonl")
    ms = sorted(glob.glob(pat))
    if ms:
        session_file = ms[0]
    else:
        print("FAIL\tno_session_file")
        raise SystemExit(0)

expected = set(t.strip() for t in tools_csv.split(",") if t.strip())
assistant_toolcall = False
tool_result_seen = False
matched_expected = False

with open(session_file, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") != "message":
            continue
        m = obj.get("message") or {}
        role = m.get("role")
        if role == "assistant":
            for item in m.get("content") or []:
                if item.get("type") != "toolCall":
                    continue
                nm = str(item.get("name") or "")
                if not nm:
                    continue
                assistant_toolcall = True
                if (not expected) or (nm in expected) or ("tool_call" in expected and nm == "exec"):
                    matched_expected = True
        elif role == "toolResult":
            tname = str(m.get("toolName") or "")
            if tname:
                tool_result_seen = True
                if (not expected) or (tname in expected) or ("tool_call" in expected and tname == "exec"):
                    matched_expected = True

if (assistant_toolcall or tool_result_seen) and matched_expected:
    print("PASS\treal_tool_evidence")
else:
    print("FAIL\tno_real_tool_evidence")
PY
)"
        local ev_code="${ev_out%%$'\t'*}"
        local ev_reason="${ev_out#*$'\t'}"
        if [[ "$ev_code" == "PASS" ]]; then
          echo "INFO: summary empty but session has real tool evidence ($ev_reason)" | tee -a "$LOG"
        else
          echo "HARD_FAIL: finished has empty summary and no tool evidence ($ev_reason)" | tee -a "$LOG"
          ((JOB_FAIL++)) || true
          if [[ "$JOB_PASS" -gt 0 ]]; then
            ((JOB_PASS--)) || true
          fi
        fi
      fi

      if [[ "$VERIFY_SEND" == "1" ]]; then
        # 应发送：message 中抽取的 tool_* 含 tool_send_*
        local vs_out
        vs_out="$("$PY_BIN" - <<'PY' "$found_json" "$HOME" "${agent_id:-}" "${session_id:-}" "$tools_csv" "${job_id:-}"
import glob
import json
import os
import re
import sys

def is_send_tool(name: str) -> bool:
    if not isinstance(name, str):
        return False
    if name == "tool_analyze_after_close_and_send_daily_report":
        return True
    # 进程内采集并发送：会话 toolResult 的 toolName 为复合工具，非 tool_send_*
    if name in (
        "tool_run_opening_analysis_and_send",
        "tool_run_before_open_analysis_and_send",
        "tool_run_signal_risk_inspection_and_send",
        "tool_run_tail_session_analysis_and_send",
        "tool_run_midday_recap_and_send",
    ):
        return True
    return name.startswith("tool_send_")

def coverage_below_gate(obj: dict) -> bool:
    """
    门禁对齐：
    - 若发送工具返回 data.coverage.ratio 且 < 0.20，则视为发送失败
    """
    if not isinstance(obj, dict):
        return False
    data = obj.get("data")
    if not isinstance(data, dict):
        return False
    coverage = data.get("coverage")
    if not isinstance(coverage, dict):
        return False
    ratio = coverage.get("ratio")
    try:
        return float(ratio) < 0.20
    except Exception:
        return False

def tool_result_send_success(m: dict) -> str:
    """Return ok | fail | unknown for a toolResult on tool_send_*."""
    if m.get("role") != "toolResult":
        return "unknown"
    if not is_send_tool(m.get("toolName") or ""):
        return "unknown"
    if m.get("isError"):
        return "fail"
    d = m.get("details")
    if isinstance(d, dict):
        if coverage_below_gate(d):
            return "fail"
        if d.get("success") is True:
            # success=True + skipped=True：同日幂等/重复调用跳过，仍视为发送链路 OK（无第二条消息属预期）
            if d.get("skipped") is True:
                return "ok"
            resp = d.get("response")
            if isinstance(resp, dict):
                ec = resp.get("errcode")
                if ec == 0:
                    return "ok"
                if ec not in (None, 0):
                    return "fail"
            return "ok"
        if d.get("success") is False:
            return "fail"
    for item in m.get("content") or []:
        if item.get("type") != "text":
            continue
        t = (item.get("text") or "").strip()
        if not t:
            continue
        try:
            o = json.loads(t)
        except Exception:
            if re.search(r'"success"\s*:\s*true', t) and re.search(r'"errcode"\s*:\s*0', t):
                return "ok"
            if re.search(r'"success"\s*:\s*false', t):
                return "fail"
            continue
        if o.get("success") is True:
            if o.get("skipped") is True:
                return "ok"
            if coverage_below_gate(o):
                return "fail"
            r = o.get("response")
            if isinstance(r, dict) and r.get("errcode") not in (None, 0):
                return "fail"
            return "ok"
        if o.get("success") is False:
            return "fail"
    return "unknown"

def scan_session(path: str):
    """(attempted_send, any_ok, any_explicit_fail, structured_daily_ok)

    structured_daily_ok: tool_send_daily_report or tool_send_analysis_report returned ok
    (excludes tool_send_dingtalk_message-only success).
    """
    attempted = False
    any_ok = False
    any_fail = False
    structured_daily_ok = False
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("type") != "message":
                continue
            m = obj.get("message") or {}
            role = m.get("role")
            if role == "assistant":
                for item in m.get("content") or []:
                    if item.get("type") == "toolCall" and is_send_tool(item.get("name") or ""):
                        attempted = True
            if role == "toolResult" and is_send_tool(m.get("toolName") or ""):
                attempted = True
                tname = m.get("toolName") or ""
                verdict = tool_result_send_success(m)
                if verdict == "ok":
                    any_ok = True
                    if tname in (
                        "tool_send_daily_report",
                        "tool_send_analysis_report",
                        "tool_analyze_after_close_and_send_daily_report",
                        "tool_run_before_open_analysis_and_send",
                    ):
                        structured_daily_ok = True
                elif verdict == "fail":
                    any_fail = True
    return attempted, any_ok, any_fail, structured_daily_ok

# 与 ~/.openclaw/cron/jobs.json「etf: 每日市场分析报告」一致：验收须为结构化日报投递，钉钉短消息不算。
STRUCTURED_DAILY_MARKET_JOB_IDS = frozenset({"8c548101-85b7-4c95-a458-8b0e15317d46"})
STRUCTURED_BEFORE_OPEN_JOB_IDS = frozenset({"572f20f2-fa1d-4e25-9e0b-fbcccf366790"})

finished_s = sys.argv[1]
home = sys.argv[2]
agent_id = sys.argv[3] or ""
session_id = (sys.argv[4] or "").strip()
tools_csv = sys.argv[5] or ""
job_id = (sys.argv[6] or "").strip()

if (
    "tool_send_" not in tools_csv
    and "tool_analyze_after_close_and_send_daily_report" not in tools_csv
    and "tool_run_opening_analysis_and_send" not in tools_csv
    and "tool_run_signal_risk_inspection_and_send" not in tools_csv
    and "tool_run_before_open_analysis_and_send" not in tools_csv
    and "tool_run_tail_session_analysis_and_send" not in tools_csv
    and "tool_run_midday_recap_and_send" not in tools_csv
):
    print("SKIP\tno send-related tool in message\t")
    sys.exit(0)

try:
    rec = json.loads(finished_s)
except Exception as e:
    print("FAIL\tbad finished json\t%s" % e)
    sys.exit(0)

finished_status = rec.get("status")
delivered = rec.get("delivered")
delivery_status = (rec.get("deliveryStatus") or "") or ""
summary = rec.get("summary") or ""

# 0) 防“假工具调用 / 假 JSON”护栏：summary 出现伪 tool_call 片段直接判失败
# 说明：真实工具调用不应出现在 summary 文本中；出现通常意味着模型跑偏或在“伪造执行过程”。
if re.search(r"(?is)<tool_call>|<function=|<parameter=|\\btype\\s*[:=]\\s*\"?toolcall\"?|\"type\"\\s*:\\s*\"toolCall\"", summary):
    print("FAIL\tfake tool call markers in summary\t")
    sys.exit(0)
if re.search(r"(?is)```json\\s*\\{\\s*\"type\"\\s*:\\s*\"toolCall\"", summary):
    print("FAIL\tfake toolCall json block in summary\t")
    sys.exit(0)

# 0) 巡检快报模板护栏（弱校验）：若 summary 看起来是巡检快报，则末行应为 INSPECTION_RUN_STATUS 且无尾随内容
if "宽基ETF巡检快报" in summary:
    if re.search(r"(?i)\\b(strong|moderate|weak|hold|after_close|closed)\\b", summary):
        print("FAIL\\tinspection contains leaked english state tokens\\t")
        sys.exit(0)
    m = re.search(r"(?m)^INSPECTION_RUN_STATUS:\\s*(\\S+)\\s*$", summary)
    # 注意：部分运行 summary 会被框架压缩/改写，缺少尾行时不应在此提前失败，
    # 后续会继续从 session toolResult 证据判断是否真实投递成功。
    if m:
        # 应以该行结束（允许尾部空白）
        tail = summary[m.end():].strip()
        if tail:
            print("FAIL\\tinspection has trailing content after status\\t")
            sys.exit(0)
        status_token = (m.group(1) or "").strip().lower()
        allowed = {"ok","partial","data_source_degraded","dingtalk_fail","error","success"}
        if status_token not in allowed:
            print("FAIL\\tinspection status token invalid\\t%s" % status_token)
            sys.exit(0)

# 1) OpenClaw 投递层成功（与 delivery.mode 配置有关；mode=none 时常为假阴性）
if delivered is True or str(delivery_status).lower() == "delivered":
    print("PASS\tframework delivery\tdelivered=%s deliveryStatus=%s" % (delivered, delivery_status))
    sys.exit(0)

if finished_status != "ok":
    print("FAIL\tfinished status=%s\t%s" % (finished_status, rec.get("error") or ""))
    sys.exit(0)

# 2) 会话文件：~/.openclaw/agents/<agentId>/sessions/<sessionId>.jsonl
#    必须在 summary 里的 ERROR_NO_DELIVERY_TOOL_CALL 之前扫描：复合工具（如
#    tool_run_tail_session_analysis_and_send）若已成功，应以 toolResult 为准，避免
#    模型在 summary 中误带错误提示导致假失败。
session_file = None
if session_id and session_id not in ("None", "null"):
    cand = os.path.join(home, ".openclaw", "agents", agent_id, "sessions", session_id + ".jsonl")
    if os.path.isfile(cand):
        session_file = cand
    else:
        pat = os.path.join(home, ".openclaw", "agents", "*", "sessions", session_id + ".jsonl")
        matches = sorted(glob.glob(pat))
        if matches:
            session_file = matches[0]

attempted = False
any_ok = False
any_fail = False
structured_daily_ok = False
if session_file:
    attempted, any_ok, any_fail, structured_daily_ok = scan_session(session_file)

require_structured_daily = job_id in STRUCTURED_DAILY_MARKET_JOB_IDS
require_structured_before_open = job_id in STRUCTURED_BEFORE_OPEN_JOB_IDS

# 3) 判定：必须有一次发送工具的成功 toolResult；仅有调用无成功则失败
#    每日市场分析任务：必须 tool_send_daily_report / tool_send_analysis_report 成功（钉钉短消息不算）。
#    结构化日报/盘前：禁止仅凭 finished.summary 弱关键词通过（模型易编造「已发送」而未产生 toolResult）。
if require_structured_daily or require_structured_before_open:
    if structured_daily_ok:
        print(
            "PASS\tsession structured send (daily|before_open|analysis_report)\t%s" % session_file
        )
        sys.exit(0)
    if any_ok:
        print(
            "FAIL\tstructured report required but only other tool_send_* succeeded\t%s" % session_file
        )
        sys.exit(0)
    if not session_file:
        print("FAIL\tno session file for sessionId=%s agentId=%s" % (session_id, agent_id))
        sys.exit(0)
    if require_structured_before_open:
        print(
            "FAIL\tstructured before_open requires successful tool_run_before_open_analysis_and_send (or tool_send_daily_report) in session; assistant text alone is invalid\t%s"
            % session_file
        )
    else:
        print(
            "FAIL\tstructured daily requires successful tool_analyze_after_close_and_send_daily_report (or tool_send_daily_report) in session; assistant text alone is invalid\t%s"
            % session_file
        )
    sys.exit(0)
else:
    if any_ok:
        print("PASS\tsession tool_send_* success\t%s" % session_file)
        sys.exit(0)

if re.search(r"ERROR_NO_DELIVERY_TOOL_CALL", summary):
    print("FAIL\tprompt marker ERROR_NO_DELIVERY_TOOL_CALL\t")
    sys.exit(0)

summary_ok = bool(
    re.search(
        r"已发送|发送成功|successfully delivered|飞书通知已发送|钉钉.*已发送|errcode\"\s*:\s*0|投递成功",
        summary,
        re.I,
    )
)
if any_fail and not any_ok:
    print("FAIL\tsession tool_send_* returned failure\t%s" % session_file)
    sys.exit(0)
if attempted and not any_ok:
    print("FAIL\ttool_send_* called but no successful toolResult\t%s" % session_file)
    sys.exit(0)
if summary_ok:
    print("PASS\tsummary hint only (weak)\t")
    sys.exit(0)
if not session_file:
    print("FAIL\tno session file for sessionId=%s agentId=%s" % (session_id, agent_id))
    sys.exit(0)
print("FAIL\tno send success in session and no summary hint\t%s" % session_file)
sys.exit(0)
PY
)"
        # vs_out: PASS|FAIL|SKIP <tab> reason <tab> detail
        local vs_code="${vs_out%%$'\t'*}"
        local vs_rest="${vs_out#*$'\t'}"
        local vs_reason="${vs_rest%%$'\t'*}"
        local vs_detail="${vs_rest#*$'\t'}"
        case "$vs_code" in
          PASS)
            ((SEND_OK++)) || true
            echo "VERIFY_SEND: PASS — $vs_reason ${vs_detail:+($vs_detail)}" | tee -a "$LOG"
            ;;
          FAIL)
            ((SEND_FAIL++)) || true
            echo "VERIFY_SEND: FAIL — $vs_reason ${vs_detail:+($vs_detail)}" | tee -a "$LOG"
            if [[ "$HARD_FAIL_ON_MISSING_SEND" == "1" ]]; then
              ((JOB_FAIL++)) || true
              if [[ "$JOB_PASS" -gt 0 ]]; then
                ((JOB_PASS--)) || true
              fi
              echo "HARD_FAIL: verify_send; sessionId=$session_id agentId=$agent_id" | tee -a "$LOG"
            fi
            ;;
          SKIP)
            ((SEND_UNKNOWN++)) || true
            echo "VERIFY_SEND: SKIP — $vs_reason" | tee -a "$LOG"
            ;;
          *)
            ((SEND_FAIL++)) || true
            echo "VERIFY_SEND: PARSE_ERROR raw=${vs_out:-<empty>}" | tee -a "$LOG"
            ;;
        esac
      fi
    fi
  fi

  echo "" | tee -a "$LOG"
}

if [[ ! -f "$JOBS_JSON" ]]; then
  echo "找不到 jobs.json: $JOBS_JSON" | tee -a "$LOG"
  exit 1
fi

if [[ "$MODE" != "tools" && "$MODE" != "cron" ]]; then
  echo "不支持的 --mode: $MODE (应为 tools|cron)" | tee -a "$LOG"
  exit 2
fi

if [[ ! -x "${RUNNER%% *}" ]]; then
  echo "未找到虚拟环境 python: ${RUNNER%% *}，请先创建/激活 .venv" | tee -a "$LOG"
  exit 1
fi

# 预处理：一次性从 jobs.json 抽取每个任务的工具列表
JOBS_PLAN_JSONL="$(
"$PY_BIN" - <<'PY' "$JOBS_JSON" "$FILTER_REGEX"
import json, re, sys

path = sys.argv[1]
flt = sys.argv[2] if len(sys.argv) > 2 else ""
rx_tool = re.compile(r"\btool_[A-Za-z0-9_]+")
rx_flt = re.compile(flt) if flt else None

obj = json.load(open(path, "r", encoding="utf-8"))
for j in obj.get("jobs", []):
    jid = j.get("id", "")
    name = j.get("name", "")
    enabled = bool(j.get("enabled", True))
    payload = j.get("payload") or {}
    msg = payload.get("message") or ""

    if rx_flt and not (rx_flt.search(jid) or rx_flt.search(name)):
        continue

    tools = []
    seen = set()
    for t in rx_tool.findall(msg):
        if t not in seen:
            tools.append(t)
            seen.add(t)

    out = {
        "id": jid,
        "name": name,
        "enabled": enabled,
        "agentId": j.get("agentId") or "",
        "timeoutSeconds": payload.get("timeoutSeconds"),
        "tools": tools,
        "message": msg,
    }
    print(json.dumps(out, ensure_ascii=False))
PY
)"

if [[ -z "$JOBS_PLAN_JSONL" ]]; then
  echo "未匹配到任何任务（filter=${FILTER_REGEX:-<none>}）" | tee -a "$LOG"
  exit 0
fi

echo "--- 开始批量测试 ---" | tee -a "$LOG"
echo "" | tee -a "$LOG"

while IFS= read -r job_line; do
  [[ -z "$job_line" ]] && continue
  job_id="$(echo "$job_line" | jq -r '.id')"
  job_name="$(echo "$job_line" | jq -r '.name')"
  enabled="$(echo "$job_line" | jq -r '.enabled')"
  tools_csv="$(echo "$job_line" | jq -r '.tools | join(",")')"
  agent_id="$(echo "$job_line" | jq -r '.agentId // ""')"
  job_timeout_sec="$(echo "$job_line" | jq -r 'if (.timeoutSeconds | type) == "number" then .timeoutSeconds | floor else empty end')"
  payload_message="$(echo "$job_line" | jq -r '.message // ""')"

  if [[ "$MODE" == "cron" ]]; then
    run_job_cron "$job_id" "$job_name" "$enabled" "$tools_csv" "$agent_id" "$job_timeout_sec" "$payload_message"
  else
    run_job_tools "$job_id" "$job_name" "$enabled" "$tools_csv"
  fi
done <<<"$JOBS_PLAN_JSONL"

echo "--- 汇总 ---" | tee -a "$LOG"
echo "任务: 通过 $JOB_PASS, 失败 $JOB_FAIL, 跳过 $JOB_SKIP" | tee -a "$LOG"
echo "工具调用: 通过 $PASS, 失败 $FAIL, 跳过 $SKIP" | tee -a "$LOG"
if [[ "$MODE" == "cron" && "$VERIFY_SEND" == "1" ]]; then
  echo "发送校验: 通过 $SEND_OK, 失败 $SEND_FAIL, 跳过/未知 $SEND_UNKNOWN" | tee -a "$LOG"
fi
