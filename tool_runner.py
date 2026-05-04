#!/usr/bin/env python3
"""
OpenClaw工具调用脚本
通过命令行参数调用不同的工具函数
从本地目录导入工具并执行
"""

import sys
import json
import os
from pathlib import Path
import io
from contextlib import redirect_stdout, redirect_stderr
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel, ValidationError

# 始终使用当前脚本所在目录作为项目根，保证可导入 src / plugins
project_root = Path(__file__).parent
plugins_dir = project_root / "plugins"
if plugins_dir.exists():
    sys.path.insert(0, str(plugins_dir))
sys.path.insert(0, str(project_root))


def _load_dotenv_for_tools() -> None:
    """
    与 OpenClaw Gateway 对齐：从项目根 .env 与 ~/.openclaw/.env 注入环境变量。
    使用 plugins/utils/env_loader：无 python-dotenv 时仍可解析 KEY=VALUE。
    override=False：已在 shell 中 export 的值优先。
    """
    try:
        from utils.env_loader import load_env_file
    except ImportError:
        return
    load_env_file(project_root / ".env", override=False)
    load_env_file(Path.home() / ".openclaw" / ".env", override=False)


_load_dotenv_for_tools()

# 旧工具名 -> (新工具名, 注入参数) 用于兼容 cron/工作流
# 数据采集类 tool_fetch_* / tool_read_* 已迁至 Gateway 插件 openclaw-data-china-stock，此处不再做别名映射。
def _coerce_cli_value(raw: str) -> Any:
    """将 key=value 中的 value 转为 bool / int / float / str。"""
    s = raw.strip()
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "none"):
        return None
    if s.isdigit():
        # 保留前导零代码（如 000300）为字符串，避免 json.loads 以外的 CLI 路径丢零
        if len(s) > 1 and s.startswith("0"):
            return s
        try:
            return int(s)
        except ValueError:
            pass
    if s.startswith("-") and len(s) > 1 and s[1:].isdigit():
        try:
            return int(s)
        except ValueError:
            pass
    try:
        if "." in s or "e" in low:
            return float(s)
    except ValueError:
        pass
    return s


def _parse_tool_cli_args(argv_tail: List[str]) -> Dict[str, Any]:
    """
    解析 tool_runner 在工具名之后的参数。

    - 无参数：{}
    - 单参数且以 @ 开头：从文件读 JSON
    - 单参数且以 { 开头：JSON 对象
    - 否则：若每个 token 均含 ``=``，按 key=value 解析（value 可含逗号，如多标的）
    - 单参数其它情况：仍尝试 json.loads（兼容旧行为）
    """
    if not argv_tail:
        return {}
    if len(argv_tail) == 1 and argv_tail[0].startswith("@"):
        arg_path = Path(argv_tail[0][1:]).expanduser()
        if not arg_path.is_file():
            raise FileNotFoundError(f"参数文件不存在: {arg_path}")
        text = arg_path.read_text(encoding="utf-8")
        return json.loads(text) if text.strip() else {}
    first = argv_tail[0].strip()
    if len(argv_tail) == 1 and first.startswith("{"):
        return json.loads(first)
    if all("=" in x for x in argv_tail):
        out: Dict[str, Any] = {}
        for item in argv_tail:
            k, _, v = item.partition("=")
            key = k.strip()
            if not key:
                continue
            out[key] = _coerce_cli_value(v)
        return out
    if len(argv_tail) == 1:
        return json.loads(argv_tail[0])
    raise ValueError(
        "参数须为 JSON 对象、@文件路径，或多个 key=value（例如 underlying=510300,510500 index_code=000300,000905）"
    )


ALIASES = {
    "tool_fetch_index_realtime": ("tool_fetch_index_data", {"data_type": "realtime"}),
    "tool_fetch_index_historical": ("tool_fetch_index_data", {"data_type": "historical"}),
    "tool_fetch_index_minute": ("tool_fetch_index_data", {"data_type": "minute"}),
    "tool_fetch_index_opening": ("tool_fetch_index_data", {"data_type": "opening"}),
    "tool_fetch_global_index_spot": ("tool_fetch_index_data", {"data_type": "global_spot"}),
    "tool_fetch_global_index_hist_sina": ("tool_fetch_global_index_hist_sina", {}),
    "tool_fetch_etf_realtime": ("tool_fetch_etf_data", {"data_type": "realtime"}),
    "tool_send_feishu_message": ("tool_send_feishu_notification", {"notification_type": "message"}),
    "tool_send_signal_alert": ("tool_send_feishu_notification", {"notification_type": "signal_alert"}),
    "tool_send_risk_alert": ("tool_send_feishu_notification", {"notification_type": "risk_alert"}),
    "tool_analyze_after_close": ("tool_analyze_market", {"moment": "after_close"}),
    "tool_analyze_before_open": ("tool_analyze_market", {"moment": "before_open"}),
    "tool_analyze_opening_market": ("tool_analyze_market", {"moment": "opening"}),
    "tool_predict_volatility": ("tool_volatility", {"mode": "predict"}),
    "tool_calculate_historical_volatility": ("tool_volatility", {"mode": "historical"}),
    "tool_calculate_position_size": ("tool_position_limit", {"action": "calculate"}),
    "tool_check_position_limit": ("tool_position_limit", {"action": "check"}),
    "tool_apply_hard_limit": ("tool_position_limit", {"action": "apply"}),
    "tool_calculate_stop_loss_take_profit": ("tool_stop_loss_take_profit", {"action": "calculate"}),
    "tool_check_stop_loss_take_profit": ("tool_stop_loss_take_profit", {"action": "check"}),
    "tool_get_strategy_performance": ("tool_strategy_analytics", {"action": "performance"}),
    "tool_calculate_strategy_score": ("tool_strategy_analytics", {"action": "score"}),
    "tool_get_strategy_weights": ("tool_strategy_weights", {"action": "get"}),
    "tool_adjust_strategy_weights": ("tool_strategy_weights", {"action": "adjust"}),
}

class TradingCopilotParams(BaseModel):
    focus_etfs: Optional[str] = None
    focus_stocks: Optional[str] = None
    mode: Optional[str] = "normal"
    run_signal: Optional[bool] = False
    signal_etf: Optional[str] = None
    throttle_minutes: Optional[int] = 5
    timezone: Optional[str] = "Asia/Shanghai"
    disable_network_fetch: Optional[bool] = False
    output_format: Optional[str] = "feishu_card"
    include_snapshot: Optional[bool] = False
    send_feishu_card: Optional[bool] = False
    feishu_webhook_url: Optional[str] = None


class ToolSpec(BaseModel):
    module_path: str
    function_name: str
    params_model: Optional[Type[BaseModel]] = None
    """调用前将参数名从 key 映射为 value，例如 underlying -> symbol"""
    param_mapping: Optional[Dict[str, str]] = None


# 统一错误码（供 Agent/工作流分支处理）
TOOL_ERROR_CODES = {
    "VALIDATION_ERROR": "参数校验失败",
    "UNKNOWN_TOOL": "未知工具",
    "IMPORT_ERROR": "导入错误",
    "RUNTIME_ERROR": "执行异常",
}


# 工具函数映射（与 config/tools_manifest.json 对齐；数据采集由 openclaw-data-china-stock 在 Gateway 注册）
# merged.fetch_* 仍供 copilot / 分析模块 Python 导入；实现来自 plugins.data_collection（符号链接至外部插件仓库）
TOOL_MAP: Dict[str, ToolSpec] = {
    # 保留：供 tool_fetch_global_index_spot 别名与 copilot 内部调用
    "tool_fetch_index_data": ToolSpec(
        module_path="merged.fetch_index_data",
        function_name="tool_fetch_index_data",
    ),
    "tool_fetch_global_index_hist_sina": ToolSpec(
        module_path="plugins.data_collection.index.fetch_global_hist_sina",
        function_name="tool_fetch_global_index_hist_sina",
    ),
    "tool_fetch_etf_data": ToolSpec(
        module_path="merged.fetch_etf_data",
        function_name="tool_fetch_etf_data",
    ),
    # Data-collection tools (implemented in openclaw-data-china-stock extension; available via symlinked plugins/data_collection)
    "tool_fetch_stock_realtime": ToolSpec(
        module_path="plugins.data_collection.stock.fetch_realtime",
        function_name="tool_fetch_stock_realtime",
    ),
    "tool_fetch_stock_historical": ToolSpec(
        module_path="plugins.data_collection.stock.fetch_historical",
        function_name="tool_fetch_stock_historical",
    ),
    "tool_fetch_stock_minute": ToolSpec(
        module_path="plugins.data_collection.stock.fetch_minute",
        function_name="tool_fetch_stock_minute",
    ),
    "tool_fetch_etf_iopv_snapshot": ToolSpec(
        module_path="plugins.data_collection.etf.fetch_realtime",
        function_name="tool_fetch_etf_iopv_snapshot",
    ),
    "tool_get_option_contracts": ToolSpec(
        module_path="plugins.data_collection.utils.get_contracts",
        function_name="tool_get_option_contracts",
    ),
    "tool_internal_alert_scan": ToolSpec(
        module_path="analysis.internal_alert_scan",
        function_name="tool_internal_alert_scan",
    ),
    "tool_trading_copilot": ToolSpec(
        module_path="copilot.trading_copilot",
        function_name="tool_trading_copilot",
        params_model=TradingCopilotParams,
    ),
    "tool_event_sentinel": ToolSpec(
        module_path="sentinel.event_sentinel",
        function_name="tool_event_sentinel",
    ),
    "tool_send_feishu_card_webhook": ToolSpec(
        module_path="notification.send_feishu_card_webhook",
        function_name="tool_send_feishu_card_webhook",
    ),
    "tool_calculate_technical_indicators_unified": ToolSpec(
        module_path="analysis.technical_indicators_unified",
        function_name="tool_calculate_technical_indicators_unified",
    ),
    "tool_generate_signals": ToolSpec(
        module_path="src.signal_generation",
        function_name="tool_generate_signals",
    ),
    "tool_generate_option_trading_signals": ToolSpec(
        module_path="src.signal_generation",
        function_name="tool_generate_option_trading_signals",
    ),
    "tool_generate_etf_trading_signals": ToolSpec(
        module_path="src.etf_signal_generation",
        function_name="tool_generate_etf_trading_signals",
    ),
    "tool_generate_stock_trading_signals": ToolSpec(
        module_path="src.stock_signal_generation",
        function_name="tool_generate_stock_trading_signals",
    ),
    "tool_assess_risk": ToolSpec(
        module_path="analysis.risk_assessment",
        function_name="tool_assess_risk",
    ),
    "tool_compute_index_key_levels": ToolSpec(
        module_path="analysis.key_levels",
        function_name="tool_compute_index_key_levels",
    ),
    "tool_get_yesterday_prediction_review": ToolSpec(
        module_path="analysis.accuracy_tracker",
        function_name="tool_get_yesterday_prediction_review",
    ),
    "tool_record_before_open_prediction": ToolSpec(
        module_path="analysis.accuracy_tracker",
        function_name="tool_record_before_open_prediction",
    ),
    "tool_predict_intraday_range": ToolSpec(
        module_path="analysis.intraday_range",
        function_name="tool_predict_intraday_range",
        param_mapping={"underlying": "symbol"},
    ),
    "tool_predict_daily_volatility_range": ToolSpec(
        module_path="analysis.daily_volatility_range",
        function_name="tool_predict_daily_volatility_range",
        param_mapping={"underlying": "symbol"},
    ),
    "tool_analyze_market": ToolSpec(
        module_path="merged.analyze_market",
        function_name="tool_analyze_market",
    ),
    "tool_volatility": ToolSpec(
        module_path="merged.volatility",
        function_name="tool_volatility",
    ),
    "tool_underlying_historical_snapshot": ToolSpec(
        module_path="analysis.underlying_historical_snapshot",
        function_name="tool_underlying_historical_snapshot",
    ),
    "tool_historical_snapshot": ToolSpec(
        module_path="analysis.underlying_historical_snapshot",
        function_name="tool_historical_snapshot",
    ),
    "tool_check_etf_index_consistency": ToolSpec(
        module_path="analysis.etf_trend_tracking",
        function_name="tool_check_etf_index_consistency",
    ),
    "tool_generate_trend_following_signal": ToolSpec(
        module_path="analysis.etf_trend_tracking",
        function_name="tool_generate_trend_following_signal",
    ),
    "tool_strategy_engine": ToolSpec(
        module_path="strategy_engine.tool_strategy_engine",
        function_name="tool_strategy_engine",
    ),
    "tool_nlu_query": ToolSpec(
        module_path="plugins.nlu.intent_router",
        function_name="tool_nlu_query",
    ),
    "tool_detect_market_regime": ToolSpec(
        module_path="analysis.market_regime",
        function_name="tool_detect_market_regime",
    ),
    "tool_etf_rotation_research": ToolSpec(
        module_path="analysis.etf_rotation_research",
        function_name="tool_etf_rotation_research",
    ),
    "tool_strategy_research": ToolSpec(
        module_path="analysis.strategy_research",
        function_name="tool_strategy_research",
    ),
    "tool_position_limit": ToolSpec(
        module_path="merged.position_limit",
        function_name="tool_position_limit",
    ),
    "tool_stop_loss_take_profit": ToolSpec(
        module_path="merged.stop_loss_take_profit",
        function_name="tool_stop_loss_take_profit",
    ),
    "tool_record_signal_effect": ToolSpec(
        module_path="analysis.strategy_tracker",
        function_name="tool_record_signal_effect",
    ),
    "tool_strategy_analytics": ToolSpec(
        module_path="merged.strategy_analytics",
        function_name="tool_strategy_analytics",
    ),
    "tool_strategy_weights": ToolSpec(
        module_path="merged.strategy_weights",
        function_name="tool_strategy_weights",
    ),
    "tool_send_feishu_notification": ToolSpec(
        module_path="merged.send_feishu_notification",
        function_name="tool_send_feishu_notification",
    ),
    "tool_send_dingtalk_message": ToolSpec(
        module_path="notification.send_dingtalk_message",
        function_name="tool_send_dingtalk_message",
    ),
    "tool_send_signal_risk_inspection": ToolSpec(
        module_path="notification.send_signal_risk_inspection",
        function_name="tool_send_signal_risk_inspection",
    ),
    "tool_run_signal_risk_inspection_and_send": ToolSpec(
        module_path="notification.run_signal_risk_inspection",
        function_name="tool_run_signal_risk_inspection_and_send",
    ),
    "tool_run_midday_recap_and_send": ToolSpec(
        module_path="notification.run_midday_recap",
        function_name="tool_run_midday_recap_and_send",
    ),
    "tool_run_opening_analysis_and_send": ToolSpec(
        module_path="notification.run_opening_analysis",
        function_name="tool_run_opening_analysis_and_send",
    ),
    "tool_run_tail_session_analysis_and_send": ToolSpec(
        module_path="notification.run_tail_session_analysis",
        function_name="tool_run_tail_session_analysis_and_send",
    ),
    "tool_run_before_open_analysis_and_send": ToolSpec(
        module_path="notification.run_before_open_analysis",
        function_name="tool_run_before_open_analysis_and_send",
    ),
    "tool_run_data_cache_job": ToolSpec(
        module_path="data_collection.run_data_cache_job",
        function_name="tool_run_data_cache_job",
    ),
    "tool_send_analysis_report": ToolSpec(
        module_path="notification.send_analysis_report",
        function_name="tool_send_analysis_report",
    ),
    "tool_send_etf_rotation_research_report": ToolSpec(
        module_path="notification.send_etf_rotation_research",
        function_name="tool_send_etf_rotation_research_report",
    ),
    "tool_send_etf_rotation_research_last_report": ToolSpec(
        module_path="notification.send_etf_rotation_research_last_report",
        function_name="tool_send_etf_rotation_research_last_report",
    ),
    "tool_send_daily_report": ToolSpec(
        module_path="notification.send_daily_report",
        function_name="tool_send_daily_report",
    ),
    "tool_analyze_after_close_and_send_daily_report": ToolSpec(
        module_path="notification.send_daily_report",
        function_name="tool_analyze_after_close_and_send_daily_report",
    ),
    "tool_portfolio_risk_snapshot": ToolSpec(
        module_path="risk.portfolio_risk_snapshot",
        function_name="tool_portfolio_risk_snapshot",
    ),
    "tool_screen_equity_factors": ToolSpec(
        module_path="plugins.analysis.equity_factor_screening",
        function_name="tool_screen_equity_factors",
    ),
    "tool_screen_by_factors": ToolSpec(
        module_path="plugins.analysis.equity_factor_screening",
        function_name="tool_screen_by_factors",
    ),
    "tool_l4_valuation_context": ToolSpec(
        module_path="plugins.analysis.l4_data_tools",
        function_name="tool_l4_valuation_context",
    ),
    "tool_l4_pe_ttm_percentile": ToolSpec(
        module_path="plugins.analysis.l4_data_tools",
        function_name="tool_l4_pe_ttm_percentile",
    ),
    "tool_l4_portfolio_valuation_context": ToolSpec(
        module_path="plugins.analysis.l4_compose.portfolio_tool",
        function_name="tool_l4_portfolio_valuation_context",
    ),
    "tool_plugin_catalog_digest": ToolSpec(
        module_path="plugins.catalog_digest_upstream",
        function_name="tool_plugin_catalog_digest",
    ),
    "tool_summarize_attempts": ToolSpec(
        module_path="plugins.attempts_rollup_upstream",
        function_name="tool_summarize_attempts",
    ),
    "tool_finalize_screening_nightly": ToolSpec(
        module_path="src.screening_ops",
        function_name="tool_finalize_screening_nightly",
    ),
    "tool_set_screening_emergency_pause": ToolSpec(
        module_path="src.screening_ops",
        function_name="tool_set_screening_emergency_pause",
    ),
    "tool_sector_heat_score": ToolSpec(
        module_path="data_collection.limit_up.sector_heat",
        function_name="tool_sector_heat_score",
    ),
    # A 股资金流向（实现位于 openclaw-data-china-stock 的 plugins/data_collection，主仓 symlink）
    "tool_capital_flow": ToolSpec(
        module_path="plugins.data_collection.capital_flow",
        function_name="tool_capital_flow",
    ),
    "tool_fetch_a_share_fund_flow": ToolSpec(
        module_path="plugins.data_collection.a_share_fund_flow",
        function_name="tool_fetch_a_share_fund_flow",
    ),
    "tool_resolve_symbol": ToolSpec(
        module_path="plugins.data_collection.entity.entity_tools",
        function_name="tool_resolve_symbol",
    ),
    "tool_get_entity_meta": ToolSpec(
        module_path="plugins.data_collection.entity.entity_tools",
        function_name="tool_get_entity_meta",
    ),
    "tool_backtest_limit_up_pullback": ToolSpec(
        module_path="backtest.limit_up_pullback",
        function_name="tool_backtest_limit_up_pullback",
    ),
    "tool_backtest_limit_up_sensitivity": ToolSpec(
        module_path="backtest.limit_up_pullback",
        function_name="tool_backtest_limit_up_sensitivity",
    ),
    "tool_llm_json_extract": ToolSpec(
        module_path="utils.llm_structured_extract",
        function_name="tool_llm_json_extract",
    ),
}

def main():
    if len(sys.argv) < 2:
        print(
            json.dumps(
                {
                    "error": "缺少工具名称",
                    "usage": "python3 tool_runner.py <tool_name> [@path/to/args.json | JSON对象 | key=value ...]",
                }
            )
        )
        sys.exit(1)

    tool_name = sys.argv[1]
    argv_tail = sys.argv[2:]

    # 解析参数：JSON 对象 / @path / key=value ...
    try:
        args = _parse_tool_cli_args(argv_tail)
    except FileNotFoundError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
    except (json.JSONDecodeError, ValueError) as e:
        print(json.dumps({"error": f"参数格式错误: {e}"}, ensure_ascii=False))
        sys.exit(1)
    
    # 别名解析：旧工具名 -> 新工具名 + 注入参数（兼容 cron/工作流）
    if tool_name in ALIASES:
        new_name, inject = ALIASES[tool_name]
        args = {**inject, **args}
        tool_name = new_name
    
    # 查找工具
    if tool_name not in TOOL_MAP:
        print(
            json.dumps(
                {
                    "error": f"未知工具: {tool_name}",
                    "error_code": TOOL_ERROR_CODES["UNKNOWN_TOOL"],
                    "available_tools": list(TOOL_MAP.keys()),
                },
                ensure_ascii=False,
            )
        )
        sys.exit(1)

    spec = TOOL_MAP[tool_name]
    module_path, function_name = spec.module_path, spec.function_name

    # 可选：记录执行耗时与结果（环境变量 OPTION_TRADING_ASSISTANT_LOG_TOOL_EXEC=1 时启用）
    log_tool_exec = os.environ.get("OPTION_TRADING_ASSISTANT_LOG_TOOL_EXEC", "").strip() in ("1", "true", "yes")
    start_time = __import__("time").time() if log_tool_exec else None

    # 动态导入并调用工具函数
    #
    # 重要：部分依赖库/配置加载器会把日志打印到 stdout，干扰 cron/脚本对 JSON 输出的解析。
    # 这里将工具执行过程中的 stdout/stderr 捕获起来，保证 tool_runner 的最终输出始终是“纯 JSON”。
    buf_out = io.StringIO()
    buf_err = io.StringIO()
    try:
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            module = __import__(module_path, fromlist=[function_name])
            tool_func: Callable[..., Any] = getattr(module, function_name)

            # 如果定义了 Pydantic 参数模型，优先做结构化校验与转换
            if spec.params_model is not None:
                try:
                    model_instance = spec.params_model(**args)
                    args = model_instance.model_dump()
                except ValidationError as ve:
                    print(
                        json.dumps(
                            {
                                "error": "参数校验失败",
                                "error_code": "VALIDATION_ERROR",
                                "details": json.loads(ve.json()),
                            },
                            ensure_ascii=False,
                        )
                    )
                    sys.exit(1)

            # 显式参数名映射（见 ToolSpec.param_mapping）
            if spec.param_mapping:
                for from_key, to_key in spec.param_mapping.items():
                    if from_key in args:
                        args[to_key] = args.pop(from_key)

            # 调用工具函数
            result = tool_func(**args)

        if log_tool_exec and start_time is not None:
            duration_ms = round((__import__("time").time() - start_time) * 1000)
            import logging
            logging.getLogger(__name__).info(
                "tool_exec %s duration_ms=%d success=true", tool_name, duration_ms
            )
        # 输出结果（JSON格式）
        print(json.dumps(result, ensure_ascii=False, default=str))
    except ImportError as e:
        if log_tool_exec and start_time is not None:
            duration_ms = round((__import__("time").time() - start_time) * 1000)
            import logging
            logging.getLogger(__name__).info(
                "tool_exec %s duration_ms=%d success=false error_code=IMPORT_ERROR", tool_name, duration_ms
            )
        payload = {
            "error": f"导入错误: {e}",
            "error_code": TOOL_ERROR_CODES["IMPORT_ERROR"],
            "module": module_path,
            "function": function_name,
        }
        if buf_out.getvalue().strip():
            payload["captured_stdout"] = buf_out.getvalue()[-2000:]
        if buf_err.getvalue().strip():
            payload["captured_stderr"] = buf_err.getvalue()[-2000:]
        print(json.dumps(payload, ensure_ascii=False, default=str))
        sys.exit(1)
    except Exception as e:
        if log_tool_exec and start_time is not None:
            duration_ms = round((__import__("time").time() - start_time) * 1000)
            import logging
            logging.getLogger(__name__).info(
                "tool_exec %s duration_ms=%d success=false error_code=RUNTIME_ERROR", tool_name, duration_ms
            )
        payload = {
            "error": str(e),
            "error_code": TOOL_ERROR_CODES["RUNTIME_ERROR"],
            "type": type(e).__name__,
        }
        if buf_out.getvalue().strip():
            payload["captured_stdout"] = buf_out.getvalue()[-2000:]
        if buf_err.getvalue().strip():
            payload["captured_stderr"] = buf_err.getvalue()[-2000:]
        print(json.dumps(payload, ensure_ascii=False, default=str))
        sys.exit(1)

if __name__ == "__main__":
    main()
