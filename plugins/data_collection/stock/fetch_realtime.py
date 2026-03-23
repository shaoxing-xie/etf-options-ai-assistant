"""
获取A股股票实时数据。

Provider 顺序（与 `providers/stock_realtime.py`、`ROADMAP.md` 一致）：
1. mootdx / TDX（通达信远程，非纯 HTTP）→ _fetch_realtime_mootdx
2. 东财五档（可选，单票）→ stock_bid_ask_em，quote_type=depth
3. 腾讯 HTTP（qt.gtimg.cn）→ _fetch_realtime_tencent
4. AkShare 全市场快照筛选（stock_zh_a_spot）→ _fetch_realtime_akshare
"""

from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import logging
import os
import sys

logger = logging.getLogger(__name__)

try:
    from mootdx.quotes import Quotes
    import tdxpy.hq as _tdx_hq
    MOOTDX_AVAILABLE = True
except ImportError:
    MOOTDX_AVAILABLE = False

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False


def _ensure_utils_import():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
    utils_path = os.path.join(parent_dir, "utils")
    if utils_path not in sys.path:
        sys.path.insert(0, utils_path)


_ensure_utils_import()

try:
    from plugins.utils.trading_day import check_trading_day_before_operation
    TRADING_DAY_CHECK_AVAILABLE = True
except ImportError:
    TRADING_DAY_CHECK_AVAILABLE = False

    def check_trading_day_before_operation(*args, **kwargs):
        return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _normalize_stock_code(code: str) -> str:
    """
    规范股票代码为6位数字形式（去掉交易所后缀或前缀）
    """
    cc = code.strip()
    if cc.upper().endswith((".SH", ".SZ", ".BJ")):
        cc = cc.split(".")[0]
    if cc.lower().startswith(("sh", "sz", "bj")) and len(cc) > 2:
        cc = cc[2:]
    return cc


def _fetch_realtime_mootdx(codes: List[str]) -> Optional[List[Dict[str, Any]]]:
    """
    使用 mootdx/TDX 获取股票实时行情（主数据源）
    对应 a-share-real-time-data SKILL 能力。
    """
    if not MOOTDX_AVAILABLE:
        logger.warning("mootdx/TDX 不可用：当前 Python 环境无法导入 mootdx（MOOTDX_AVAILABLE=False）")
        return None
    try:
        # 绕过 tdxpy 的交易时间限制
        try:
            _tdx_hq.time_frame = lambda: True  # type: ignore[attr-defined]
        except Exception:
            pass

        client = Quotes.factory(market="std")
        # 转换成纯数字代码列表
        symbols = [_normalize_stock_code(c) for c in codes]
        df = client.quotes(symbol=symbols)
        if df is None or df.empty:
            return None

        # 匹配时统一用规范化代码：mootdx 可能返回 "600519" 或 "600519.SH"
        code_series = df.get("code")
        if code_series is None:
            return None
        code_str = code_series.astype(str)
        try:
            df_normalized = code_str.map(lambda c: _normalize_stock_code(c))
        except Exception:
            df_normalized = code_str

        results: List[Dict[str, Any]] = []
        for orig, sym in zip(codes, symbols):
            row = None
            try:
                match = df[df_normalized == sym]
                if not match.empty:
                    row = match.iloc[0]
                else:
                    continue
            except Exception:
                continue

            price = _safe_float(row.get("price"))
            open_p = _safe_float(row.get("open"))
            high = _safe_float(row.get("high"))
            low = _safe_float(row.get("low"))
            prev_close = _safe_float(row.get("last_close"))
            volume = _safe_int(row.get("vol"))
            amount = _safe_float(row.get("amount"))

            change = 0.0
            change_pct = 0.0
            if prev_close:
                change = price - prev_close
                change_pct = change / prev_close * 100

            name = str(row.get("name") or "")

            results.append(
                {
                    "stock_code": orig,
                    "name": name,
                    "current_price": price,
                    "change": change,
                    "change_percent": change_pct,
                    "open": open_p,
                    "high": high,
                    "low": low,
                    "prev_close": prev_close,
                    "volume": volume,
                    "amount": amount,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

        return results if results else None
    except Exception:
        return None


def _to_qt_symbol(code: str) -> str:
    """转为腾讯行情 API 的代码格式：sh600519 / sz000001"""
    c = _normalize_stock_code(code)
    if not c:
        return "sh" + code.strip()
    if c.startswith("6"):
        return "sh" + c
    if c.startswith(("0", "3")) or c.startswith("4"):
        return "sz" + c
    return "sh" + c


def _fetch_realtime_tencent(codes: List[str]) -> Optional[List[Dict[str, Any]]]:
    """
    使用腾讯行情 qt.gtimg.cn 获取股票实时行情（兜底，不依赖 akshare/mootdx）
    返回格式与 mootdx/akshare 一致，便于上层统一处理。
    """
    import urllib.request
    import urllib.error

    if not codes:
        return None
    try:
        q = ",".join(_to_qt_symbol(c) for c in codes)
        url = f"https://qt.gtimg.cn/q={q}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            # qt.gtimg.cn 通常为 GBK 编码；若解码失败再降级为 UTF-8
            try:
                text = raw.decode("gbk", errors="replace")
            except Exception:
                text = raw.decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, Exception):
        return None

    results: List[Dict[str, Any]] = []
    # 格式: v_sh600519="1~贵州茅台~600519~1401.18~1426.19~1415.00~48014~...";
    for line in text.strip().split(";"):
        line = line.strip()
        if not line.startswith("v_") or "=" not in line:
            continue
        try:
            name_part, data_part = line.split("=", 1)
            raw = data_part.strip('"').strip("'")
            parts = raw.split("~")
            if len(parts) < 6:
                continue
            # 常见顺序：名称、代码、现价、昨收、今开、成交量...
            name = parts[1] if len(parts) > 1 else ""
            code = parts[2] if len(parts) > 2 else ""
            current_price = _safe_float(parts[3] if len(parts) > 3 else 0)
            prev_close = _safe_float(parts[4] if len(parts) > 4 else 0)
            open_p = _safe_float(parts[5] if len(parts) > 5 else 0)
            volume = _safe_int(parts[6] if len(parts) > 6 else 0)  # 腾讯为手
            high = _safe_float(parts[33] if len(parts) > 33 else 0) or current_price
            low = _safe_float(parts[34] if len(parts) > 34 else 0) or current_price
            amount = _safe_float(parts[37] if len(parts) > 37 else 0)
            change = current_price - prev_close if prev_close else 0.0
            change_pct = change / prev_close * 100 if prev_close else 0.0
            results.append(
                {
                    "stock_code": code or _normalize_stock_code(name_part.replace("v_", "")),
                    "name": name,
                    "current_price": current_price,
                    "change": change,
                    "change_percent": change_pct,
                    "open": open_p,
                    "high": high,
                    "low": low,
                    "prev_close": prev_close,
                    "volume": volume,
                    "amount": amount,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
        except (IndexError, ValueError, TypeError):
            continue
    return results if results else None


def _fetch_realtime_akshare(codes: List[str]) -> Optional[List[Dict[str, Any]]]:
    """
    使用 AkShare 全市场快照获取实时行情（兜底数据源）
    调用 ak.stock_zh_a_spot() 一次性拉取新浪财经 A 股实时快照（全市场），返回 DataFrame。
    """
    if not AKSHARE_AVAILABLE:
        return None
    try:
        df = ak.stock_zh_a_spot()
        if df is None or df.empty:
            return None

        # 规范成纯数字代码
        clean_codes = [_normalize_stock_code(c) for c in codes]

        code_col = None
        for col in ["代码", "code", "股票代码", "证券代码"]:
            if col in df.columns:
                code_col = col
                break
        if not code_col:
            return None

        results: List[Dict[str, Any]] = []
        for orig_code, clean_code in zip(codes, clean_codes):
            row = None
            try:
                match = df[df[code_col].astype(str) == clean_code]
                if not match.empty:
                    row = match.iloc[0]
            except Exception:
                row = None

            if row is None:
                continue

            name = ""
            for name_col in ["名称", "name", "股票名称", "证券简称"]:
                if name_col in row.index:
                    try:
                        name_val = str(row[name_col])
                        if name_val and name_val != "nan":
                            name = name_val
                            break
                    except Exception:
                        continue

            current_price = 0.0
            for price_col in ["最新价", "最新", "现价", "close", "价格"]:
                if price_col in row.index:
                    current_price = _safe_float(row[price_col])
                    if current_price != 0:
                        break

            prev_close = 0.0
            for pc_col in ["昨收", "昨收盘", "前收盘", "pre_close"]:
                if pc_col in row.index:
                    prev_close = _safe_float(row[pc_col])
                    if prev_close != 0:
                        break

            change_val = 0.0
            for ch_col in ["涨跌额", "change"]:
                if ch_col in row.index:
                    change_val = _safe_float(row[ch_col])
                    if change_val != 0:
                        break

            change_percent_val = 0.0
            for pct_col in ["涨跌幅", "涨跌幅%", "pct_chg"]:
                if pct_col in row.index:
                    change_percent_val = _safe_float(row[pct_col])
                    if change_percent_val != 0:
                        break

            if prev_close and current_price and change_val == 0:
                change_val = current_price - prev_close
            if prev_close and change_val and change_percent_val == 0:
                change_percent_val = change_val / prev_close * 100

            open_price = 0.0
            for oc in ["今开", "开盘价", "open"]:
                if oc in row.index:
                    open_price = _safe_float(row[oc])
                    if open_price != 0:
                        break

            high = 0.0
            for hc in ["最高", "最高价", "high"]:
                if hc in row.index:
                    high = _safe_float(row[hc])
                    if high != 0:
                        break

            low = 0.0
            for lc in ["最低", "最低价", "low"]:
                if lc in row.index:
                    low = _safe_float(row[lc])
                    if low != 0:
                        break

            volume = 0.0
            for vc in ["成交量", "volume", "成交量(手)"]:
                if vc in row.index:
                    volume = _safe_float(row[vc])
                    if volume != 0:
                        break

            amount = 0.0
            for ac in ["成交额", "amount"]:
                if ac in row.index:
                    amount = _safe_float(row[ac])
                    if amount != 0:
                        break

            results.append(
                {
                    "stock_code": orig_code,
                    "name": name,
                    "current_price": current_price,
                    "change": change_val,
                    "change_percent": change_percent_val,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "prev_close": prev_close,
                    "volume": volume,
                    "amount": amount,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

        return results if results else None
    except Exception:
        return None


STOCK_REALTIME_CHAIN_ORDER: Tuple[str, ...] = (
    "mootdx",
    "eastmoney_bid_ask",
    "qt.gtimg.cn",
    "stock_zh_a_spot",
)


def _fetch_bid_ask_em_single(code: str) -> Optional[List[Dict[str, Any]]]:
    """东财五档盘口（单票），失败返回 None。用于与快照链互补。"""
    if not AKSHARE_AVAILABLE:
        return None
    c = _normalize_stock_code(code)
    try:
        df = ak.stock_bid_ask_em(symbol=c)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    row = df.iloc[0]
    sell1 = None
    buy1 = None
    for col in df.columns:
        cs = str(col)
        if "卖" in cs and "价" in cs:
            try:
                sell1 = float(row[col])
            except (TypeError, ValueError):
                pass
        if "买" in cs and "价" in cs:
            try:
                buy1 = float(row[col])
            except (TypeError, ValueError):
                pass
    mid = None
    if sell1 is not None and buy1 is not None:
        mid = (sell1 + buy1) / 2.0
    elif sell1 is not None:
        mid = sell1
    elif buy1 is not None:
        mid = buy1
    if mid is None:
        return None
    return [
        {
            "stock_code": code.strip(),
            "name": "",
            "current_price": mid,
            "change": 0.0,
            "change_percent": 0.0,
            "open": 0.0,
            "high": 0.0,
            "low": 0.0,
            "prev_close": 0.0,
            "volume": 0,
            "amount": 0.0,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "quote_type": "depth",
        }
    ]


def run_stock_realtime_chain(
    codes: List[str],
    *,
    mode: str = "production",
    include_depth: bool = True,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str], Dict[str, Any]]:
    """
    A 股实时 Provider 链（供 OpenClaw 与单测）。返回 (rows, source, debug)。
    """
    debug: Dict[str, Any] = {
        "chain": list(STOCK_REALTIME_CHAIN_ORDER),
        "attempted": [],
        "notes": [],
    }
    results: Optional[List[Dict[str, Any]]] = None
    source: Optional[str] = None

    debug["attempted"].append("mootdx")
    results = _fetch_realtime_mootdx(codes)
    if results:
        return results, "mootdx", debug

    if include_depth and len(codes) == 1 and AKSHARE_AVAILABLE:
        debug["attempted"].append("eastmoney_bid_ask")
        depth = _fetch_bid_ask_em_single(codes[0])
        if depth:
            return depth, "eastmoney_bid_ask", debug

    debug["attempted"].append("qt.gtimg.cn")
    results = _fetch_realtime_tencent(codes)
    if results:
        return results, "qt.gtimg.cn", debug

    debug["attempted"].append("stock_zh_a_spot")
    results = _fetch_realtime_akshare(codes)
    if results:
        return results, "stock_zh_a_spot", debug

    debug["notes"].append("所有实时 Provider 均未返回数据")
    return None, None, debug


def fetch_stock_realtime(
    stock_code: str = "600000",
    mode: str = "production",
    include_depth: bool = True,
) -> Dict[str, Any]:
    """
    获取A股股票实时数据，支持多股票代码（逗号分隔）
    """
    debug: Dict[str, Any] = {}
    if mode == "test":
        debug = {
            "sys_executable": sys.executable,
            "mootdx_available": MOOTDX_AVAILABLE,
            "attempt_order": list(STOCK_REALTIME_CHAIN_ORDER),
            "attempted": [],
            "notes": [],
        }

    # 记录当前 Python 环境与 mootdx 可用性，便于排查为何未走 mootdx
    try:
        logger.info(
            "fetch_stock_realtime: sys.executable=%s, MOOTDX_AVAILABLE=%s, codes_input=%s, mode=%s",
            sys.executable,
            MOOTDX_AVAILABLE,
            stock_code,
            mode,
        )
    except Exception:
        pass

    # 交易日检查
    if TRADING_DAY_CHECK_AVAILABLE and mode != "test":
        trading_day_check = check_trading_day_before_operation("获取股票实时数据")
        if trading_day_check:
            return trading_day_check

    if isinstance(stock_code, str):
        codes = [c.strip() for c in stock_code.split(",") if c.strip()]
    elif isinstance(stock_code, list):
        codes = [str(c).strip() for c in stock_code if str(c).strip()]
    else:
        codes = [str(stock_code).strip()]

    if not codes:
        return {"success": False, "message": "未提供有效的股票代码", "data": None}

    results, source, chain_debug = run_stock_realtime_chain(
        codes, mode=mode, include_depth=include_depth
    )
    if mode == "test":
        debug = {**debug, **chain_debug}

    if not results:
        logger.warning(
            "tool_fetch_stock_realtime 所有数据源均失败: codes=%s",
            codes,
        )
        ret = {
            "success": False,
            "message": "无法获取股票实时行情（mootdx、东财五档、腾讯 qt.gtimg.cn、AkShare stock_zh_a_spot 均不可用或返回空数据）",
            "data": None,
            "source": source or "none",
            "count": 0,
        }
        if mode == "test":
            ret["debug"] = debug
        return ret

    used_source = source or "unknown"
    logger.info(
        "tool_fetch_stock_realtime 成功: codes=%s, source=%s, count=%s",
        codes,
        used_source,
        len(results),
    )
    ret = {
        "success": True,
        "message": "Successfully fetched stock realtime data",
        "data": results[0] if len(results) == 1 else results,
        "source": used_source,
        "count": len(results),
    }
    if mode == "test":
        ret["debug"] = debug
    return ret


def tool_fetch_stock_realtime(
    stock_code: str = "600000",
    mode: str = "production",
    include_depth: bool = True,
) -> Dict[str, Any]:
    """
    OpenClaw 工具：获取股票实时数据
    """
    return fetch_stock_realtime(
        stock_code=stock_code, mode=mode, include_depth=include_depth
    )

