"""
获取指数开盘数据（9:28 集合竞价）
融合原系统 fetch_index_opening_data，OpenClaw 插件工具
优先新浪 stock_zh_index_spot_sina()，东财 stock_zh_index_spot_em 备用
"""

import pandas as pd
from typing import Optional, Dict, Any, List
from datetime import datetime
import os
import sys

# 导入交易日判断工具
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
utils_path = os.path.join(parent_dir, 'utils')
if utils_path not in sys.path:
    sys.path.insert(0, utils_path)

try:
    from plugins.utils.trading_day import check_trading_day_before_operation
    TRADING_DAY_CHECK_AVAILABLE = True
except ImportError:
    TRADING_DAY_CHECK_AVAILABLE = False
    def check_trading_day_before_operation(*args, **kwargs):
        return None

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False

# 默认指数代码（与原系统一致，逗号分隔）
DEFAULT_INDEX_CODES = "000001,399006,399001,000688,000300,899050"

# 指数代码与名称映射（用于匹配与兜底名称）
INDEX_MAPPING = {
    "000001": "上证指数",
    "399006": "创业板指",
    "399001": "深证成指",
    "000688": "科创50",
    "000300": "沪深300",
    "899050": "北证50",
    "000016": "上证50",
    "000905": "中证500",
    "000852": "中证1000",
}


def _safe_get(row: pd.Series, *keys: str, default: float = 0) -> float:
    """从 Series 中按多种列名安全取数"""
    for key in keys:
        if key in row.index:
            try:
                value = row[key]
                if value is not None and str(value) not in ('nan', ''):
                    return float(value)
            except (ValueError, TypeError):
                continue
    return default


def _fetch_sina() -> Optional[pd.DataFrame]:
    """主数据源：新浪 stock_zh_index_spot_sina()"""
    try:
        df = ak.stock_zh_index_spot_sina()
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    return None


def _fetch_em() -> Optional[pd.DataFrame]:
    """备用数据源：东财 stock_zh_index_spot_em(symbol=...)"""
    symbols_to_try = ["沪深重要指数", "上证系列指数", "深证系列指数", "中证系列指数"]
    all_df = None
    for symbol in symbols_to_try:
        try:
            temp_df = ak.stock_zh_index_spot_em(symbol=symbol)
            if temp_df is not None and not temp_df.empty:
                if all_df is None:
                    all_df = temp_df
                else:
                    all_df = pd.concat([all_df, temp_df], ignore_index=True)
        except Exception:
            continue
    return all_df


def _build_opening_item(
    code: str,
    row: pd.Series,
    code_col: str,
) -> Dict[str, Any]:
    """从一行 DataFrame 构建开盘数据项"""
    open_price = _safe_get(row, '今开', 'open', '开盘', '开盘价')
    pre_close = _safe_get(row, '昨收', 'close', 'close_yesterday', 'pre_close')
    change_pct = _safe_get(row, '涨跌幅', 'pct_chg', 'change_pct', '涨跌%')
    change = _safe_get(row, '涨跌额', 'change', '涨跌')
    volume = _safe_get(row, '成交量', 'volume', 'vol', '成交')
    name = INDEX_MAPPING.get(code, "未知指数")
    for name_col in ['名称', 'name', '指数名称']:
        if name_col in row.index:
            try:
                v = str(row[name_col])
                if v and v != 'nan':
                    name = v
                    break
            except Exception:
                pass
    if pre_close != 0 and change == 0 and open_price != 0:
        change = open_price - pre_close
    if pre_close != 0 and change_pct == 0 and open_price != 0:
        change_pct = (open_price - pre_close) / pre_close * 100
    return {
        "index_code": code,
        "code": code,
        "name": name,
        "opening_price": open_price,
        "pre_close": pre_close,
        "change": change,
        "change_pct": change_pct,
        "volume": volume,
        "timestamp": datetime.now().strftime("%Y-%m-%d 09:28:00"),
    }


def _extract_results(df: pd.DataFrame, index_codes: List[str]) -> List[Dict[str, Any]]:
    """从全市场 DataFrame 中按指数代码筛选并生成开盘数据列表"""
    code_col = None
    for col in ['代码', 'code', 'symbol']:
        if col in df.columns:
            code_col = col
            break
    if not code_col:
        return []

    results = []
    for code in index_codes:
        # 新浪返回 sh000001 / sz399006，东财可能为 000001 / 399006
        if code.startswith("000") or code.startswith("899"):
            possible = [f"sh{code}", code]
        elif code.startswith("399"):
            possible = [f"sz{code}", code]
        else:
            possible = [code]

        row = None
        for p in possible:
            try:
                mask = df[code_col].astype(str).str.contains(p, na=False, regex=False)
                if mask.any():
                    row = df[mask].iloc[0]
                    break
            except Exception:
                continue
        if row is not None and not row.empty:
            results.append(_build_opening_item(code, row, code_col))
    return results


def fetch_index_opening(
    index_codes: Optional[str] = None,
    mode: str = "production",
) -> Dict[str, Any]:
    """
    获取主要指数的开盘数据（9:28 集合竞价）。
    优先新浪 stock_zh_index_spot_sina()，东财 stock_zh_index_spot_em 备用。

    Args:
        index_codes: 指数代码，逗号分隔，如 "000001,000300"。默认 000001,399006,399001,000688,000300,899050
        mode: "production"（检查交易日）或 "test"（跳过检查）

    Returns:
        Dict: success, message, data(list), source
    """
    try:
        if TRADING_DAY_CHECK_AVAILABLE and mode != "test":
            trading_day_check = check_trading_day_before_operation("获取指数开盘数据")
            if trading_day_check:
                return trading_day_check

        if not AKSHARE_AVAILABLE:
            return {
                "success": False,
                "message": "akshare not installed. Please install: pip install akshare",
                "data": None,
            }

        codes_str = index_codes if index_codes else DEFAULT_INDEX_CODES
        index_codes_list = [c.strip() for c in codes_str.split(",") if c.strip()]
        if not index_codes_list:
            return {
                "success": False,
                "message": "未提供有效的指数代码",
                "data": None,
            }

        df = None
        source = None

        # 优先新浪
        df = _fetch_sina()
        if df is not None and not df.empty:
            source = "stock_zh_index_spot_sina"

        # 备用东财
        if df is None or df.empty:
            df = _fetch_em()
            if df is not None and not df.empty:
                source = "stock_zh_index_spot_em"

        if df is None or df.empty:
            return {
                "success": False,
                "message": "新浪与东财接口均未返回数据，请稍后重试",
                "data": None,
            }

        results = _extract_results(df, index_codes_list)
        if not results:
            return {
                "success": False,
                "message": "未匹配到任何目标指数数据",
                "data": None,
            }

        return {
            "success": True,
            "message": "数据获取成功",
            "data": results,
            "source": source,
            "count": len(results),
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error: {str(e)}",
            "data": None,
        }


def tool_fetch_index_opening(
    index_codes: Optional[str] = None,
    mode: str = "production",
) -> Dict[str, Any]:
    """
    OpenClaw 工具：获取指数开盘数据（9:28 集合竞价）。
    主数据源：新浪 stock_zh_index_spot_sina()；备用：东财 stock_zh_index_spot_em()。
    """
    return fetch_index_opening(index_codes=index_codes, mode=mode)
