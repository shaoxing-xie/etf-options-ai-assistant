#!/usr/bin/env bash
# 批量测试 ~/.openclaw/cron/jobs.json 中各定时任务涉及的工具
# - 读取 jobs.json，逐条任务从 payload.message 抽取 tool_*，然后用 tool_runner.py 冒烟执行
# - 默认跳过 tool_send_*（避免误发飞书/钉钉）；可用 --include-send 打开

# 不 set -e，跑完全部用例并汇总
cd "$(dirname "$0")/.."
RUNNER="./.venv/bin/python tool_runner.py"

JOBS_JSON="${JOBS_JSON:-$HOME/.openclaw/cron/jobs.json}"
OUT_DIR="./test_cron_results"
FILTER_REGEX=""
INCLUDE_DISABLED="0"
INCLUDE_SEND="0"
MODE="tools" # tools | cron
CRON_TIMEOUT_MS="1800000"
EXPECT_FINAL="0"

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

环境变量:
  JOBS_JSON=<path>           等价于 --jobs

示例:
  scripts/test_cron_tools.sh --filter "盘后|after_close"
  scripts/test_cron_tools.sh --include-disabled
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
    -h|--help) usage; exit 0 ;;
    *)
      echo "未知参数: $1"
      usage
      exit 2
      ;;
  esac
done

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
    tool_generate_signals) echo '{"underlying":"510300","mode":"test"}' ;;
    tool_assess_risk) echo '{"symbol":"510300"}' ;;
    tool_calculate_historical_volatility) echo '{"symbol":"510300","data_type":"etf_daily","lookback_days":60}' ;;
    tool_predict_volatility) echo '{"underlying":"510300"}' ;;
    tool_calculate_technical_indicators) echo '{"symbol":"510300","data_type":"etf_minute"}' ;;
    tool_check_etf_index_consistency) echo '{"etf_symbol":"510300","index_code":"000300"}' ;;
    tool_generate_trend_following_signal) echo '{"etf_symbol":"510300","index_code":"000300"}' ;;
    tool_check_stop_loss_take_profit) echo '{"action":"check","symbol":"510300"}' ;;
    tool_record_signal_effect) echo "{\"signal_id\":\"TEST_${today}\",\"signal_type\":\"buy\",\"etf_symbol\":\"510300\",\"signal_strength\":0.6,\"strategy\":\"trend_following\",\"entry_price\":4.0,\"status\":\"pending\"}" ;;
    tool_quantitative_screening) echo '{"candidates":"600000,000001,300750","lookback_days":20,"top_k":5}' ;;

    # 数据采集
    tool_fetch_index_opening) echo '{"index_code":"000300","mode":"test"}' ;;
    tool_fetch_index_realtime) echo '{"index_code":"000300","mode":"test"}' ;;
    tool_fetch_index_historical) echo '{"index_code":"000300","lookback_days":5}' ;;
    tool_fetch_index_minute) echo '{"index_code":"000300","period":"5,15,30","lookback_days":5,"mode":"test"}' ;;
    tool_fetch_global_index_spot) echo '{}' ;;

    tool_fetch_etf_realtime) echo '{"etf_code":"510300,510050,510500","mode":"test"}' ;;
    tool_fetch_etf_historical) echo '{"etf_code":"510300","lookback_days":5}' ;;
    tool_fetch_etf_minute) echo '{"etf_code":"510300","period":"5,15,30","lookback_days":5,"mode":"test"}' ;;

    tool_fetch_option_greeks) echo '{"contract_code":"10010466","mode":"test"}' ;;

    # 涨停回马枪
    tool_dragon_tiger_list) echo "{\"date\":\"${today}\"}" ;;
    tool_limit_up_daily_flow) echo '{"write_json":true,"write_report":true,"send_feishu":false}' ;;
    tool_capital_flow) echo '{"symbols":"600000,000001,300750","lookback_days":3}' ;;
    tool_fetch_northbound_flow) echo '{"lookback_days":5}' ;;

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

  echo "=== JOB $job_id (cron run) ===" | tee -a "$LOG"
  echo "name: $job_name" | tee -a "$LOG"
  echo "enabled: $enabled" | tee -a "$LOG"

  if [[ "$enabled" != "true" && "$INCLUDE_DISABLED" != "1" ]]; then
    echo "SKIP: disabled (use --include-disabled to include)" | tee -a "$LOG"
    ((JOB_SKIP++)) || true
    ((SKIP++)) || true
    echo "" | tee -a "$LOG"
    return 0
  fi

  # 注意：cron run 会按任务真实 payload 执行，可能触发真实外部通知/投递
  local cmd=(openclaw cron run "$job_id" --timeout "$CRON_TIMEOUT_MS")
  if [[ "$EXPECT_FINAL" == "1" ]]; then
    cmd+=(--expect-final)
  fi
  echo -n "--- $job_name (openclaw cron run) ... " | tee -a "$LOG"
  if out=$("${cmd[@]}" 2>&1); then
    echo "OK" | tee -a "$LOG"
    echo "$out" | head -c 1200 >> "$LOG"
    echo "" >> "$LOG"
    ((JOB_PASS++)) || true
  else
    echo "FAIL" | tee -a "$LOG"
    echo "$out" | head -c 1600 >> "$LOG"
    echo "" >> "$LOG"
    ((JOB_FAIL++)) || true
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
python3 - <<'PY' "$JOBS_JSON" "$FILTER_REGEX"
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
        "timeoutSeconds": payload.get("timeoutSeconds"),
        "tools": tools,
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

  if [[ "$MODE" == "cron" ]]; then
    run_job_cron "$job_id" "$job_name" "$enabled"
  else
    run_job_tools "$job_id" "$job_name" "$enabled" "$tools_csv"
  fi
done <<<"$JOBS_PLAN_JSONL"

echo "--- 汇总 ---" | tee -a "$LOG"
echo "任务: 通过 $JOB_PASS, 失败 $JOB_FAIL, 跳过 $JOB_SKIP" | tee -a "$LOG"
echo "工具调用: 通过 $PASS, 失败 $FAIL, 跳过 $SKIP" | tee -a "$LOG"
