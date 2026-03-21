"""
获取全球指数实时数据
融合 Coze 插件 get_index_global_spot.py
OpenClaw 插件工具

数据源优先级：
1. yfinance (Yahoo Finance)：主源，需安装 yfinance，可访问国外网站时稳定。
   安装：pip install yfinance（建议在项目 .venv 中安装）
2. 新浪 hq.sinajs.cn：兜底，易 403 Forbidden。
"""

import re
from typing import Optional, Dict, Any, List
from datetime import datetime

# 默认使用 yfinance 符号（雅虎财经标准）
DEFAULT_SYMBOLS_YF = ["^DJI", "^IXIC", "^GSPC", "^N225", "^HSI"]
# 新浪旧代码 -> yfinance 符号（兼容旧参数）
SINA_TO_YF = {
    "int_dji": "^DJI",
    "int_nasdaq": "^IXIC",
    "int_sp500": "^GSPC",
    "int_nikkei": "^N225",
    "rt_hkHSI": "^HSI",
    "int_hs": "^HSI",
    "rt_hk": "^HSI",
}
# 指数名称（用于展示）
SYMBOL_NAME_MAP = {
    "^DJI": "道琼斯",
    "^IXIC": "纳斯达克",
    "^GSPC": "标普500",
    "^N225": "日经225",
    "^HSI": "恒生指数",
}

# 兼容：保留旧常量名供外部引用（默认指数代码列表）
DEFAULT_CODES = DEFAULT_SYMBOLS_YF.copy()
CODE_NAME_MAP = SYMBOL_NAME_MAP


def _normalize_codes(index_codes: Optional[str]) -> List[str]:
    """将用户输入的 index_codes 转为 yfinance 符号列表。"""
    if not index_codes:
        return DEFAULT_SYMBOLS_YF.copy()
    if isinstance(index_codes, list):
        raw = [str(c).strip() for c in index_codes if str(c).strip()]
    else:
        raw = [c.strip() for c in str(index_codes).split(",") if c.strip()]
    if not raw:
        return DEFAULT_SYMBOLS_YF.copy()
    out = []
    for c in raw:
        if c in SINA_TO_YF:
            out.append(SINA_TO_YF[c])
        elif c.startswith("^") or (len(c) <= 6 and c.isalnum()):
            out.append(c)
        else:
            out.append(SINA_TO_YF.get(c, c))
    return out if out else DEFAULT_SYMBOLS_YF.copy()


def _fetch_yfinance(symbols: List[str]) -> Dict[str, Any]:
    """使用 yfinance 拉取全球指数，返回统一格式。"""
    try:
        import yfinance as yf
    except ImportError:
        return {"success": False, "data": [], "message": "未安装 yfinance"}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data_list = []
    for sym in symbols:
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="5d")
            if hist is None or hist.empty:
                info = t.info
                price = info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose")
                change = info.get("regularMarketChange")
                change_pct = info.get("regularMarketChangePercent")
                name = info.get("shortName") or info.get("longName") or SYMBOL_NAME_MAP.get(sym, sym)
            else:
                price = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price
                change = price - prev if len(hist) >= 2 else None
                change_pct = (change / prev * 100) if (prev and prev != 0 and change is not None) else None
                name = SYMBOL_NAME_MAP.get(sym, sym)
            data_list.append({
                "code": sym,
                "name": name,
                "price": price,
                "change": change,
                "change_pct": round(change_pct, 4) if change_pct is not None else None,
                "timestamp": now,
            })
        except Exception:
            continue
    return {
        "success": len(data_list) > 0,
        "data": data_list,
        "source": "yfinance",
    }


def _fetch_sina(codes_sina: List[str]) -> Dict[str, Any]:
    """新浪接口兜底（易 403）。入参为新浪代码如 int_dji, rt_hkHSI。"""
    import requests
    url = f"http://hq.sinajs.cn/list={','.join(codes_sina)}"
    headers = {
        "Referer": "https://finance.sina.com.cn/money/globalindex/index.shtml",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        text = response.content.decode("gbk", errors="ignore")
    except Exception as e:
        return {"success": False, "data": [], "message": str(e)}
    if not text or not text.strip():
        return {"success": False, "data": [], "message": "新浪返回空"}
    # 新浪代码 -> 名称
    sina_name = {"int_dji": "道琼斯", "int_nasdaq": "纳斯达克", "int_sp500": "标普500", "int_nikkei": "日经225", "rt_hkHSI": "恒生指数"}
    data_list = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hsi_codes = ["rt_hkHSI", "HSI", "rt_hk", "int_hs"]
    for code in codes_sina:
        try:
            try_codes = hsi_codes if any(h in code.lower() for h in ["hsi", "hs", "hk"]) else [code]
            match = None
            for tc in try_codes:
                m = re.search(rf'var hq_str_{re.escape(tc)}="([^"]+)";', text)
                if m:
                    match = m
                    break
            if not match:
                continue
            fields = [f.strip() for f in match.group(1).split(",")]
            is_hsi = code in hsi_codes or "hsi" in code.lower()
            if is_hsi and len(fields) >= 9:
                name = fields[1] or sina_name.get(code, code)
                price = float(fields[2]) if fields[2] else None
                change = float(fields[7]) if len(fields) > 7 and fields[7] else None
                cp = fields[8] if len(fields) > 8 else None
                change_pct = None
                if cp:
                    try:
                        change_pct = float(str(cp).replace("%", "").strip())
                    except ValueError:
                        if price and change and price != 0:
                            change_pct = change / price * 100
            elif len(fields) >= 6:
                name = fields[0] or sina_name.get(code, code)
                price = float(fields[1]) if fields[1] else None
                change = float(fields[2]) if fields[2] else None
                change_pct = float(fields[3]) if fields[3] else None
            else:
                continue
            data_list.append({
                "code": code,
                "name": name,
                "price": price,
                "change": change,
                "change_pct": round(change_pct, 4) if change_pct is not None else None,
                "timestamp": now,
            })
        except Exception:
            continue
    return {
        "success": len(data_list) > 0,
        "data": data_list,
        "source": "hq.sinajs.cn",
    }


def fetch_global_index_spot(
    index_codes: Optional[str] = None,
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    获取全球指数实时数据。优先 yfinance，失败则尝试新浪。
    支持参数：int_dji / ^DJI 等，默认返回道琼斯、纳斯达克、标普500、日经225、恒生。
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    symbols = _normalize_codes(index_codes)

    # 1) 优先 yfinance
    result = _fetch_yfinance(symbols)
    if result.get("success") and result.get("data"):
        return {
            "success": True,
            "count": len(result["data"]),
            "data": result["data"],
            "source": result.get("source", "yfinance"),
            "timestamp": ts,
        }

    # 2) 兜底新浪（仅支持默认 5 个指数：yf 符号转新浪代码）
    yf_to_sina = {"^DJI": "int_dji", "^IXIC": "int_nasdaq", "^GSPC": "int_sp500", "^N225": "int_nikkei", "^HSI": "rt_hkHSI"}
    codes_sina = [yf_to_sina[s] for s in symbols if s in yf_to_sina]
    if not codes_sina:
        codes_sina = ["int_dji", "int_nasdaq", "int_sp500", "int_nikkei", "rt_hkHSI"]
    fallback = _fetch_sina(codes_sina)
    if fallback.get("success") and fallback.get("data"):
        return {
            "success": True,
            "count": len(fallback["data"]),
            "data": fallback["data"],
            "source": fallback.get("source", "hq.sinajs.cn"),
            "timestamp": ts,
        }

    return {
        "success": False,
        "count": 0,
        "data": [],
        "source": "yfinance",
        "message": result.get("message", "yfinance 未安装或无数据") + "; 新浪兜底: " + fallback.get("message", "失败"),
        "timestamp": ts,
    }


def tool_fetch_global_index_spot(index_codes: Optional[str] = None) -> Dict[str, Any]:
    """OpenClaw 工具：获取全球指数实时数据。"""
    return fetch_global_index_spot(index_codes=index_codes)
