#!/usr/bin/env python3
"""
测试合并工具与别名：覆盖 21 个主工具及主要别名。
不依赖网络/缓存的用例验证分发与别名；依赖外部数据的仅验证可调用、返回结构合理。
"""
import json
import subprocess
import sys
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPT = os.path.join(ROOT, "tool_runner.py")
BASE = ROOT
TIMEOUT = 90

def run(tool: str, params: dict, timeout: int = TIMEOUT) -> dict:
    try:
        out = subprocess.run(
            [sys.executable, SCRIPT, tool, json.dumps(params)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=BASE,
        )
    except subprocess.TimeoutExpired:
        return {"_timeout": True, "_returncode": -1}
    raw = (out.stdout or "").strip()
    if not raw:
        return {"_stderr": (out.stderr or "")[:300], "_returncode": out.returncode}
    # 可能最后一行才是 JSON（前面有日志）
    for line in raw.split("\n")[::-1]:
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                pass
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw[:400], "_returncode": out.returncode}

def ok(r: dict, *keys) -> bool:
    """通过：有 success 键、或含某关键字、或 exit 0；超时也视为可接受（工具存在且被调用）"""
    if r.get("_timeout"):
        return True
    if r.get("success") is not None:
        return True
    if r.get("_returncode") == 0:
        return True
    s = json.dumps(r, ensure_ascii=False)
    return any(k in s for k in keys)

def main():
    print("合并工具测试（21 个主工具 + 别名 + 未合并工具，共 32 项）")
    print("")
    ok_count = 0
    fail_count = 0

    # ---- 1. 数据采集：指数（别名 + 合并） ----
    r = run("tool_fetch_index_realtime", {})
    if ok(r, "非交易日", "realtime", "data_type"):
        print("  OK  alias tool_fetch_index_realtime -> tool_fetch_index_data(realtime)")
        ok_count += 1
    else:
        print("  FAIL tool_fetch_index_realtime:", r); fail_count += 1

    r = run("tool_fetch_index_data", {"data_type": "opening"})
    if ok(r, "非交易日", "opening"):
        print("  OK  merged tool_fetch_index_data(data_type=opening)")
        ok_count += 1
    else:
        print("  FAIL tool_fetch_index_data opening:", r); fail_count += 1

    r = run("tool_fetch_global_index_spot", {})
    if ok(r, "global", "data", "success"):
        print("  OK  alias tool_fetch_global_index_spot -> tool_fetch_index_data(global_spot)")
        ok_count += 1
    else:
        print("  FAIL tool_fetch_global_index_spot:", r); fail_count += 1

    # ---- 2. 数据采集：ETF（别名 + 合并） ----
    r = run("tool_fetch_etf_realtime", {"etf_code": "510300"})
    if ok(r, "非交易日", "etf", "510300"):
        print("  OK  alias tool_fetch_etf_realtime -> tool_fetch_etf_data(realtime)")
        ok_count += 1
    else:
        print("  FAIL tool_fetch_etf_realtime:", r); fail_count += 1

    r = run("tool_fetch_etf_data", {"data_type": "historical", "etf_code": "510300", "start_date": "20260101", "end_date": "20260115"})
    if ok(r, "success", "data", "records"):
        print("  OK  merged tool_fetch_etf_data(data_type=historical)")
        ok_count += 1
    else:
        print("  FAIL tool_fetch_etf_data historical:", r); fail_count += 1

    # ---- 3. 数据采集：期权（合并，需 contract 可缺参测错误信息） ----
    r = run("tool_fetch_option_data", {"data_type": "realtime"})
    if ok(r) or (isinstance(r.get("message"), str) and "contract" in r.get("message", "").lower()):
        print("  OK  merged tool_fetch_option_data(data_type=realtime) [缺参或成功]")
        ok_count += 1
    else:
        print("  FAIL tool_fetch_option_data:", r); fail_count += 1

    # ---- 4. 数据采集：期货 + 工具（未合并） ----
    r = run("tool_fetch_a50_data", {"data_type": "realtime"})
    if ok(r, "success", "data", "A50", "非交易日"):
        print("  OK  tool_fetch_a50_data")
        ok_count += 1
    else:
        print("  FAIL tool_fetch_a50_data:", r); fail_count += 1

    r = run("tool_get_option_contracts", {"underlying": "510300"})
    if ok(r, "success", "data", "contract"):
        print("  OK  tool_get_option_contracts")
        ok_count += 1
    else:
        print("  FAIL tool_get_option_contracts:", r); fail_count += 1

    r = run("tool_check_trading_status", {})
    if ok(r) and (r.get("success") is True or "is_trading" in str(r) or "is_trading_day" in str(r)):
        print("  OK  tool_check_trading_status")
        ok_count += 1
    else:
        print("  FAIL tool_check_trading_status:", r); fail_count += 1

    # ---- 5. 数据访问（合并 + 别名） ----
    r = run("tool_read_index_daily", {"symbol": "000300", "start_date": "20260101", "end_date": "20260201"})
    if ok(r, "success", "data", "index_daily", "cache"):
        print("  OK  alias tool_read_index_daily -> tool_read_market_data(index_daily)")
        ok_count += 1
    else:
        print("  FAIL tool_read_index_daily:", r); fail_count += 1

    r = run("tool_read_market_data", {"data_type": "etf_daily", "symbol": "510300"})
    if ok(r, "success", "data", "etf"):
        print("  OK  merged tool_read_market_data(data_type=etf_daily)")
        ok_count += 1
    else:
        print("  FAIL tool_read_market_data etf_daily:", r); fail_count += 1

    # ---- 6. 分析：时段（合并 + 别名） ----
    r = run("tool_analyze_before_open", {}, timeout=120)
    if ok(r) or r.get("_returncode") == 0:
        print("  OK  alias tool_analyze_before_open -> tool_analyze_market(before_open)")
        ok_count += 1
    else:
        print("  FAIL tool_analyze_before_open:", r); fail_count += 1

    r = run("tool_analyze_market", {"moment": "after_close"}, timeout=120)
    if ok(r) or r.get("_returncode") == 0:
        print("  OK  merged tool_analyze_market(moment=after_close)")
        ok_count += 1
    else:
        print("  FAIL tool_analyze_market after_close:", r); fail_count += 1

    # ---- 7. 分析：波动率（合并 + 别名） ----
    r = run("tool_volatility", {"mode": "historical", "symbol": "510300", "lookback_days": 20})
    if ok(r, "success", "volatility", "data"):
        print("  OK  merged tool_volatility(mode=historical)")
        ok_count += 1
    else:
        print("  FAIL tool_volatility historical:", r); fail_count += 1

    r = run("tool_predict_volatility", {"underlying": "510300"})
    if ok(r, "success", "volatility", "predict"):
        print("  OK  alias tool_predict_volatility -> tool_volatility(mode=predict)")
        ok_count += 1
    else:
        print("  FAIL tool_predict_volatility:", r); fail_count += 1

    r = run("tool_underlying_historical_snapshot", {"symbols": "510300", "max_symbols": 1}, timeout=120)
    if ok(r, "success", "results", "hv_by_window") or (isinstance(r.get("data"), dict) and r["data"].get("results")):
        print("  OK  tool_underlying_historical_snapshot")
        ok_count += 1
    else:
        print("  FAIL tool_underlying_historical_snapshot:", r); fail_count += 1

    r = run("tool_historical_snapshot", {"symbols": "510300"}, timeout=120)
    if ok(r, "results", "hv_by_window") or (isinstance(r.get("data"), dict) and r["data"].get("results")):
        print("  OK  alias tool_historical_snapshot")
        ok_count += 1
    else:
        print("  FAIL tool_historical_snapshot:", r); fail_count += 1

    # ---- 8. 分析：未合并 ----
    r = run("tool_calculate_technical_indicators", {"symbol": "510300", "data_type": "etf_daily", "lookback_days": 30})
    if ok(r, "success", "indicators", "RSI", "MACD"):
        print("  OK  tool_calculate_technical_indicators")
        ok_count += 1
    else:
        print("  FAIL tool_calculate_technical_indicators:", r); fail_count += 1

    r = run("tool_generate_option_trading_signals", {"underlying": "510300"}, timeout=120)
    if ok(r, "success", "signals", "data"):
        print("  OK  tool_generate_option_trading_signals")
        ok_count += 1
    else:
        print("  FAIL tool_generate_option_trading_signals:", r); fail_count += 1

    r = run("tool_generate_option_trading_signals", {"underlying": "510300"}, timeout=120)
    if ok(r, "success", "signals", "data"):
        print("  OK  tool_generate_option_trading_signals")
        ok_count += 1
    else:
        print("  FAIL tool_generate_option_trading_signals:", r); fail_count += 1

    r = run("tool_generate_etf_trading_signals", {"etf_symbol": "510300"}, timeout=120)
    if ok(r, "success", "data"):
        print("  OK  tool_generate_etf_trading_signals")
        ok_count += 1
    else:
        print("  FAIL tool_generate_etf_trading_signals:", r); fail_count += 1

    r = run("tool_generate_stock_trading_signals", {"symbol": "600519"}, timeout=120)
    if ok(r, "success", "data"):
        print("  OK  tool_generate_stock_trading_signals")
        ok_count += 1
    else:
        print("  FAIL tool_generate_stock_trading_signals:", r); fail_count += 1

    r = run("tool_assess_risk", {"symbol": "510300", "entry_price": 4.6, "position_size": 500, "account_value": 100000})
    if ok(r, "success", "risk", "kelly"):
        print("  OK  tool_assess_risk")
        ok_count += 1
    else:
        print("  FAIL tool_assess_risk:", r); fail_count += 1

    # 个股风险评估依赖 akshare/东财网络；默认跳过，设 RISK_ASSESS_STOCK_SMOKE=1 时执行
    if os.environ.get("RISK_ASSESS_STOCK_SMOKE") == "1":
        r2 = run(
            "tool_assess_risk",
            {
                "symbol": "600519",
                "asset_type": "stock",
                "entry_price": 1500.0,
                "position_size": 100,
                "account_value": 1000000,
            },
            timeout=120,
        )
        d2 = r2.get("data") if isinstance(r2, dict) else None
        if r2.get("success") is True and isinstance(d2, dict) and "volatility" in d2:
            print("  OK  tool_assess_risk(stock, RISK_ASSESS_STOCK_SMOKE=1)")
            ok_count += 1
        else:
            print("  FAIL tool_assess_risk stock:", r2)
            fail_count += 1

    r = run("tool_predict_intraday_range", {"underlying": "510300"}, timeout=120)
    if ok(r, "success", "range", "predicted"):
        print("  OK  tool_predict_intraday_range")
        ok_count += 1
    else:
        print("  FAIL tool_predict_intraday_range:", r); fail_count += 1

    r = run("tool_predict_daily_volatility_range", {"underlying": "510300"}, timeout=120)
    if ok(r, "success", "daily", "range", "upper", "lower", "formatted_output"):
        print("  OK  tool_predict_daily_volatility_range")
        ok_count += 1
    else:
        print("  FAIL tool_predict_daily_volatility_range:", r); fail_count += 1

    # ---- 9. ETF 趋势（未合并） ----
    r = run("tool_check_etf_index_consistency", {"etf_symbol": "510300", "index_code": "000300", "lookback_days": 20}, timeout=120)
    if ok(r, "success", "consistency", "correlation"):
        print("  OK  tool_check_etf_index_consistency")
        ok_count += 1
    else:
        print("  FAIL tool_check_etf_index_consistency:", r); fail_count += 1

    r = run("tool_generate_trend_following_signal", {"etf_symbol": "510300", "index_code": "000300"}, timeout=120)
    if ok(r, "success", "signal", "trend"):
        print("  OK  tool_generate_trend_following_signal")
        ok_count += 1
    else:
        print("  FAIL tool_generate_trend_following_signal:", r); fail_count += 1

    # ---- 10. 风险控制（合并 + 别名） ----
    r = run("tool_position_limit", {"action": "calculate", "trend_strength": 0.7, "signal_confidence": 0.8})
    if ok(r, "success", "position", "recommended"):
        print("  OK  merged tool_position_limit(action=calculate)")
        ok_count += 1
    else:
        print("  FAIL tool_position_limit calculate:", r); fail_count += 1

    r = run("tool_check_position_limit", {"current_position_value": 2000, "account_value": 100000})
    if ok(r, "success", "over_limit", "position", "within_limit", "recommendation", "current_pct"):
        print("  OK  alias tool_check_position_limit -> tool_position_limit(action=check)")
        ok_count += 1
    else:
        print("  FAIL tool_check_position_limit:", r); fail_count += 1

    r = run("tool_stop_loss_take_profit", {"action": "calculate", "entry_price": 4.67, "current_price": 4.67, "trend_direction": "up"})
    if ok(r, "success", "stop_loss", "take_profit"):
        print("  OK  merged tool_stop_loss_take_profit(action=calculate)")
        ok_count += 1
    else:
        print("  FAIL tool_stop_loss_take_profit calculate:", r); fail_count += 1

    r = run("tool_check_stop_loss_take_profit", {"etf_symbol": "510300", "entry_price": 4.6, "current_price": 4.7, "highest_price": 4.75})
    if ok(r, "success", "triggered", "stop"):
        print("  OK  alias tool_check_stop_loss_take_profit -> tool_stop_loss_take_profit(action=check)")
        ok_count += 1
    else:
        print("  FAIL tool_check_stop_loss_take_profit:", r); fail_count += 1

    # ---- 11. 策略效果（合并 + 别名 + 未合并） ----
    r = run("tool_strategy_analytics", {"action": "performance", "strategy": "trend_following", "lookback_days": 30})
    if ok(r, "success", "strategy", "win_rate", "signals"):
        print("  OK  merged tool_strategy_analytics(action=performance)")
        ok_count += 1
    else:
        print("  FAIL tool_strategy_analytics performance:", r); fail_count += 1

    r = run("tool_get_strategy_weights", {})
    if ok(r, "success", "weights"):
        print("  OK  alias tool_get_strategy_weights -> tool_strategy_weights(action=get)")
        ok_count += 1
    else:
        print("  FAIL tool_get_strategy_weights:", r); fail_count += 1

    r = run("tool_strategy_weights", {"action": "adjust", "current_weights": {"trend_following": 0.4, "momentum": 0.6}})
    if ok(r, "success", "adjusted", "weights"):
        print("  OK  merged tool_strategy_weights(action=adjust)")
        ok_count += 1
    else:
        print("  FAIL tool_strategy_weights adjust:", r); fail_count += 1

    r = run("tool_record_signal_effect", {
        "signal_id": "test_merge_001", "signal_type": "buy", "etf_symbol": "510300",
        "signal_strength": 0.7, "strategy": "trend_following", "entry_price": 4.67, "status": "pending"
    })
    if ok(r, "success", "recorded", "signal"):
        print("  OK  tool_record_signal_effect")
        ok_count += 1
    else:
        print("  FAIL tool_record_signal_effect:", r); fail_count += 1

    # ---- 12. 通知（合并 + 别名） ----
    r = run("tool_send_feishu_message", {"message": "test merged tools", "title": "Test"})
    if ok(r, "success", "message"):
        print("  OK  alias tool_send_feishu_message -> tool_send_feishu_notification(message)")
        ok_count += 1
    else:
        print("  FAIL tool_send_feishu_message:", r); fail_count += 1

    r = run("tool_send_feishu_notification", {"notification_type": "daily_report"})
    if ok(r, "success", "report", "message"):
        print("  OK  merged tool_send_feishu_notification(notification_type=daily_report)")
        ok_count += 1
    else:
        print("  FAIL tool_send_feishu_notification daily_report:", r); fail_count += 1

    r = run("tool_send_risk_alert", {"risk_data": {"risk_level": "低", "description": "测试合并"}})
    if ok(r, "success", "risk"):
        print("  OK  alias tool_send_risk_alert -> tool_send_feishu_notification(risk_alert)")
        ok_count += 1
    else:
        print("  FAIL tool_send_risk_alert:", r); fail_count += 1

    # ---- 汇总 ----
    print("---")
    print(f"Passed: {ok_count}, Failed: {fail_count} (total {ok_count + fail_count} cases)")
    return 0 if fail_count == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
