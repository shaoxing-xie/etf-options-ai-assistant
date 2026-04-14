"""
技术指标计算插件
融合 Coze 插件 technical_indicators.py
OpenClaw 插件工具

- engine=standard（默认）：pandas_ta 向量化，RSI 为 Wilder 平滑等业界常用定义。
- engine=legacy：原 Coze 列表实现，数值与历史版本一致。
"""

import copy
import math
import logging
import re
from typing import Dict, Any, List, Optional, Tuple

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, parent_dir)

logger = logging.getLogger(__name__)

try:
    from plugins.data_access.read_cache_data import read_cache_data
except ImportError:
    def read_cache_data(*args, **kwargs):
        return {'success': False, 'df': None, 'message': 'read_cache_data not available'}

utils_path = os.path.join(parent_dir, 'utils')
if utils_path not in sys.path:
    sys.path.insert(0, utils_path)

try:
    from plugins.utils.cache import cache_result
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False
    def cache_result(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

try:
    import pandas_ta as pta  # type: ignore
    PANDAS_TA_AVAILABLE = True
except ImportError:
    pta = None  # type: ignore
    PANDAS_TA_AVAILABLE = False


def _default_technical_indicators_config() -> Dict[str, Any]:
    return {
        "engine": "standard",
        "ma_periods": [5, 10, 20, 60],
        "macd": {"fast": 12, "slow": 26, "signal": 9},
        "rsi": {"length": 14},
        "bollinger": {"length": 20, "std": 2.0},
        "kdj": {"fast_k": 9, "slow_k": 3, "slow_d": 3},
        "cci": {"length": 20},
        "adx": {"length": 14},
        "atr": {"length": 14},
        "default_indicators": ["ma", "macd", "rsi", "bollinger"],
    }


def _load_technical_indicators_config() -> Dict[str, Any]:
    cfg = _default_technical_indicators_config()
    try:
        from src.config_loader import load_system_config

        user = load_system_config(use_cache=True).get("technical_indicators")
        if not isinstance(user, dict):
            return cfg
        if user.get("engine") is not None:
            cfg["engine"] = str(user["engine"]).strip().lower()
        if user.get("ma_periods"):
            cfg["ma_periods"] = [int(x) for x in user["ma_periods"]]
        if isinstance(user.get("macd"), dict):
            m = {**cfg["macd"], **user["macd"]}
            cfg["macd"] = {"fast": int(m["fast"]), "slow": int(m["slow"]), "signal": int(m["signal"])}
        if isinstance(user.get("rsi"), dict):
            r = {**cfg["rsi"], **user["rsi"]}
            cfg["rsi"] = {"length": int(r["length"])}
        if isinstance(user.get("bollinger"), dict):
            b = {**cfg["bollinger"], **user["bollinger"]}
            cfg["bollinger"] = {"length": int(b["length"]), "std": float(b["std"])}
        if isinstance(user.get("kdj"), dict):
            k = {**cfg["kdj"], **user["kdj"]}
            cfg["kdj"] = {
                "fast_k": int(k["fast_k"]),
                "slow_k": int(k["slow_k"]),
                "slow_d": int(k["slow_d"]),
            }
        if isinstance(user.get("cci"), dict):
            c = {**cfg["cci"], **user["cci"]}
            cfg["cci"] = {"length": int(c["length"])}
        if isinstance(user.get("adx"), dict):
            a = {**cfg["adx"], **user["adx"]}
            cfg["adx"] = {"length": int(a["length"])}
        if isinstance(user.get("atr"), dict):
            t = {**cfg["atr"], **user["atr"]}
            cfg["atr"] = {"length": int(t["length"])}
        if user.get("default_indicators"):
            cfg["default_indicators"] = [str(x).strip() for x in user["default_indicators"]]
    except Exception as e:
        logger.debug("读取 technical_indicators 配置失败，使用默认值: %s", e)
    return cfg


def _normalize_ohlcv_dataframe(df: Any) -> Any:
    """统一列名、按时间升序排序；返回 pandas DataFrame。"""
    import pandas as pd

    if df is None or not hasattr(df, "copy"):
        return df
    out = df.copy()
    col_map = {
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "收盘价": "close",
    }
    for cn, en in col_map.items():
        if cn in out.columns and en not in out.columns:
            out[en] = out[cn]
    time_cols = [c for c in ("日期", "date", "time", "datetime", "trade_date") if c in out.columns]
    if time_cols:
        tc = time_cols[0]
        out[tc] = pd.to_datetime(out[tc], errors="coerce")
        out = out.sort_values(tc, ascending=True)
    out = out.reset_index(drop=True)
    return out


def _time_column_for_resample(df: Any) -> Optional[str]:
    for c in ("datetime", "time", "日期", "date", "trade_date"):
        if c in df.columns:
            return c
    return None


def _resample_minute_ohlcv(df: Any, timeframe_minutes: int) -> Any:
    """
    将分钟级 OHLCV 聚合为更大周期（如 5m -> 30m）。
    需存在可解析为时间的列；聚合规则：open 首、high 最大、low 最小、close 末、volume 求和。
    """
    import pandas as pd

    if df is None or df.empty or timeframe_minutes < 2:
        return df
    tc = _time_column_for_resample(df)
    if not tc:
        logger.warning("timeframe_minutes=%s 但未找到时间列，跳过重采样", timeframe_minutes)
        return df

    work = df.copy()
    col_map = {"开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume"}
    for cn, en in col_map.items():
        if cn in work.columns and en not in work.columns:
            work[en] = work[cn]
    work[tc] = pd.to_datetime(work[tc], errors="coerce")
    work = work.dropna(subset=[tc])
    if work.empty:
        return df

    ohlc_agg: Dict[str, str] = {}
    if "open" in work.columns:
        ohlc_agg["open"] = "first"
    if "high" in work.columns:
        ohlc_agg["high"] = "max"
    if "low" in work.columns:
        ohlc_agg["low"] = "min"
    if "close" in work.columns:
        ohlc_agg["close"] = "last"
    vol_c = None
    for c in ("volume", "vol"):
        if c in work.columns:
            vol_c = c
            break
    if vol_c:
        ohlc_agg[vol_c] = "sum"

    if "close" not in ohlc_agg:
        logger.warning("timeframe_minutes=%s 但缺少 close，跳过重采样", timeframe_minutes)
        return df

    work = work.set_index(tc).sort_index()
    rule = f"{int(timeframe_minutes)}min"
    try:
        agg = work.resample(rule, label="right", closed="right").agg(ohlc_agg)
    except Exception as e:
        logger.warning("重采样失败，使用原始数据: %s", e)
        return df
    agg = agg.dropna(how="all")
    agg = agg.reset_index()
    # 统一时间列名为 datetime，便于 data_range 展示
    if tc != "datetime" and tc in agg.columns:
        agg = agg.rename(columns={tc: "datetime"})
    elif tc == "datetime":
        pass
    else:
        first_col = agg.columns[0]
        if first_col not in ("open", "high", "low", "close"):
            agg = agg.rename(columns={first_col: "datetime"})
    return agg


def _merge_runtime_config(
    base: Dict[str, Any],
    ma_periods: Optional[List[int]],
    rsi_length: Optional[int],
) -> Dict[str, Any]:
    cfg = copy.deepcopy(base)
    if ma_periods:
        cfg["ma_periods"] = [int(x) for x in ma_periods]
    if rsi_length is not None:
        cfg["rsi"]["length"] = int(rsi_length)
    return cfg


def _normalize_indicator_names(raw: Optional[List[str]]) -> List[str]:
    """小写化指标名；忽略 MA10/RSI14 等伪项（应由 ma_periods / rsi_length 表达）。"""
    if not raw:
        return []
    out: List[str] = []
    for x in raw:
        if x is None:
            continue
        s = str(x).strip().lower()
        if re.match(r"^ma\d+$", s) or re.match(r"^rsi\d+$", s):
            continue
        if s in (
            "ma", "macd", "rsi", "bollinger", "kdj", "cci", "adx", "atr",
        ):
            out.append(s)
    return out


def _extract_shorthand_ma_rsi_periods(raw: Optional[List[str]]) -> Tuple[List[int], Optional[int]]:
    """从 ['MA10','MA20','RSI14'] 解析周期（与 normalize 配合使用）。"""
    ma_extra: List[int] = []
    rsi_len: Optional[int] = None
    if not raw:
        return [], None
    for x in raw:
        if x is None:
            continue
        s = str(x).strip()
        m = re.match(r"^ma(\d+)$", s, re.I)
        if m:
            ma_extra.append(int(m.group(1)))
            continue
        m = re.match(r"^rsi(\d+)$", s, re.I)
        if m:
            rsi_len = int(m.group(1))
    return sorted(set(ma_extra)), rsi_len


def _extract_ohlcv_series(
    df: Any,
) -> Tuple[Any, Any, Any, Any, Any]:
    """从规范化后的 DataFrame 提取 close / high / low / volume Series（pandas）。"""
    import pandas as pd

    close = None
    for c in ("close", "收盘", "收盘价"):
        if c in df.columns:
            close = pd.to_numeric(df[c], errors="coerce")
            break
    if close is None:
        for col in df.columns:
            if df[col].dtype in ("float64", "int64", "float32", "int32"):
                close = pd.to_numeric(df[col], errors="coerce")
                break
    if close is None:
        close = pd.Series(dtype=float)

    def _col(name_variants: Tuple[str, ...]) -> Any:
        for c in name_variants:
            if c in df.columns:
                return pd.to_numeric(df[c], errors="coerce")
        return None

    high = _col(("high", "最高"))
    low = _col(("low", "最低"))
    volume = _col(("volume", "成交量", "vol"))
    if high is None:
        high = close.copy()
    if low is None:
        low = close.copy()
    return close, high, low, volume


def _last_valid(series: Any) -> Optional[float]:
    import pandas as pd

    if series is None or len(series) == 0:
        return None
    s = series.dropna()
    if s.empty:
        return None
    v = float(s.iloc[-1])
    if math.isnan(v):
        return None
    return v


def _min_bars_required(indicators: List[str], cfg: Dict[str, Any]) -> int:
    req = 1
    if "ma" in indicators:
        # 与 legacy 一致：长周期 MA（如 60）可在样本不足时为 None，不要求全长数据
        p = sorted(set(int(x) for x in cfg["ma_periods"]))
        if len(p) >= 3:
            req = max(req, p[2])
        elif p:
            req = max(req, p[-1])
        if len(p) >= 2:
            req = max(req, p[1] + 1)
    if "macd" in indicators:
        m = cfg["macd"]
        # pandas_ta 在约 slow+signal-1 根起可产出末值（较 slow+signal+2 略宽松）
        req = max(req, m["slow"] + m["signal"] - 1)
    if "rsi" in indicators:
        req = max(req, cfg["rsi"]["length"] + 2)
    if "bollinger" in indicators:
        req = max(req, cfg["bollinger"]["length"] + 1)
    if "kdj" in indicators:
        k = cfg["kdj"]
        req = max(req, k["fast_k"] + k["slow_k"] + k["slow_d"] + 5)
    if "cci" in indicators:
        req = max(req, cfg["cci"]["length"] + 2)
    if "adx" in indicators:
        req = max(req, cfg["adx"]["length"] * 2 + 5)
    if "atr" in indicators:
        req = max(req, cfg["atr"]["length"] + 2)
    return max(req, 2)


def _rsi_signal_text(rsi: float) -> Tuple[str, str]:
    if rsi > 80:
        return "超买", "可能回调"
    if rsi > 70:
        return "偏强", "注意风险"
    if rsi < 20:
        return "超卖", "可能反弹"
    if rsi < 30:
        return "偏弱", "观察企稳"
    return "中性", "正常区间"


def _bollinger_signal_text(
    current: float, upper: float, lower: float, percent_b: float
) -> Tuple[str, str]:
    if current > upper:
        return "突破上轨", "可能超买或突破"
    if current < lower:
        return "突破下轨", "可能超卖或破位"
    if percent_b > 0.8:
        return "接近上轨", "注意压力"
    if percent_b < 0.2:
        return "接近下轨", "注意支撑"
    return "区间内", "正常波动"


def _standard_ma(close: Any, cfg: Dict[str, Any]) -> Dict[str, Any]:
    periods = sorted(set(int(p) for p in cfg["ma_periods"]))
    if len(periods) < 2:
        raise ValueError("ma_periods 至少需要 2 个周期")

    series_map: Dict[int, Any] = {}
    for p in periods:
        series_map[p] = pta.sma(close, length=p)

    def _val(p: int) -> Optional[float]:
        return _last_valid(series_map[p])

    if len(periods) >= 3:
        ma_vals = [_val(p) for p in periods[:3]]
        if all(v is not None for v in ma_vals):
            m0, m1, m2 = ma_vals[0], ma_vals[1], ma_vals[2]
            if m0 > m1 > m2:
                arrangement = "多头排列"
            elif m0 < m1 < m2:
                arrangement = "空头排列"
            else:
                arrangement = "交叉震荡"
        else:
            arrangement = "数据不足"
    else:
        v0, v1 = _val(periods[0]), _val(periods[1])
        if v0 is not None and v1 is not None:
            if v0 > v1:
                arrangement = "短均在上"
            elif v0 < v1:
                arrangement = "短均在下"
            else:
                arrangement = "双线贴合"
        else:
            arrangement = "数据不足"

    p_cross = periods[0]
    q_cross = periods[1]
    s0 = series_map[p_cross].dropna()
    s1 = series_map[q_cross].dropna()
    cross = "无"
    if len(s0) >= 2 and len(s1) >= 2:
        a0, b0 = float(s0.iloc[-2]), float(s0.iloc[-1])
        a1, b1 = float(s1.iloc[-2]), float(s1.iloc[-1])
        if a0 <= a1 and b0 > b1:
            cross = "金叉"
        elif a0 >= a1 and b0 < b1:
            cross = "死叉"

    current = _last_valid(close)
    ref_p = 20 if 20 in periods else periods[-1]
    ma_ref = _val(ref_p)
    price_vs = None
    if current is not None and ma_ref not in (None, 0):
        price_vs = round((current / ma_ref - 1) * 100, 2)

    out: Dict[str, Any] = {
        "arrangement": arrangement,
        "cross_signal": cross,
        "price_vs_ma20": price_vs,
        "price_vs_ref_period": ref_p,
        "periods": periods,
    }
    for p in periods:
        v = _val(p)
        out[f"ma{p}"] = round(v, 4) if v is not None else None
    return out


def _standard_macd(close: Any, cfg: Dict[str, Any]) -> Dict[str, Any]:
    m = cfg["macd"]
    macd_df = pta.macd(close, fast=m["fast"], slow=m["slow"], signal=m["signal"])
    if macd_df is None or macd_df.empty:
        return {"dif": None, "dea": None, "macd": None, "signal": "数据不足"}
    cols = macd_df.columns.tolist()
    dif_c = [c for c in cols if c.startswith("MACD_") and "MACDh" not in c and "MACDs" not in c]
    dea_c = [c for c in cols if c.startswith("MACDs_")]
    hist_c = [c for c in cols if c.startswith("MACDh_")]
    dif_s = macd_df[dif_c[0]] if dif_c else None
    dea_s = macd_df[dea_c[0]] if dea_c else None
    hist_s = macd_df[hist_c[0]] if hist_c else None
    if dif_s is None or dea_s is None:
        return {"dif": None, "dea": None, "macd": None, "signal": "数据不足"}

    d0 = dif_s.dropna()
    e0 = dea_s.dropna()
    h0 = hist_s.dropna() if hist_s is not None else None
    if len(d0) < 2 or len(e0) < 2:
        return {"dif": None, "dea": None, "macd": None, "signal": "数据不足"}

    current_dif = float(d0.iloc[-1])
    current_dea = float(e0.iloc[-1])
    current_hist = float(h0.iloc[-1]) if h0 is not None and len(h0) > 0 else (current_dif - current_dea)
    prev_hist = float(h0.iloc[-2]) if h0 is not None and len(h0) >= 2 else None

    signal = "无明显信号"
    if float(d0.iloc[-2]) <= float(e0.iloc[-2]) and current_dif > current_dea:
        signal = "金叉"
    elif float(d0.iloc[-2]) >= float(e0.iloc[-2]) and current_dif < current_dea:
        signal = "死叉"
    elif prev_hist is not None:
        if current_hist > 0 and prev_hist < current_hist:
            signal = "红柱放大"
        elif current_hist < 0 and prev_hist > current_hist:
            signal = "绿柱放大"

    return {
        "dif": round(current_dif, 4),
        "dea": round(current_dea, 4),
        "macd": round(current_hist, 4),
        "signal": signal,
    }


def _standard_rsi(close: Any, cfg: Dict[str, Any]) -> Dict[str, Any]:
    length = cfg["rsi"]["length"]
    rsi_s = pta.rsi(close, length=length)
    rsi_v = _last_valid(rsi_s)
    if rsi_v is None:
        return {"error": "数据不足", "period": length}
    sig, sug = _rsi_signal_text(rsi_v)
    return {
        "rsi": round(rsi_v, 2),
        "period": length,
        "signal": sig,
        "suggestion": sug,
    }


def _standard_bollinger(close: Any, cfg: Dict[str, Any]) -> Dict[str, Any]:
    b = cfg["bollinger"]
    bb = pta.bbands(close, length=b["length"], std=b["std"])
    if bb is None or bb.empty:
        return {"error": "数据不足"}
    row = bb.iloc[-1]
    cols = bb.columns.tolist()
    lower_c = [c for c in cols if c.startswith("BBL_")]
    mid_c = [c for c in cols if c.startswith("BBM_")]
    upper_c = [c for c in cols if c.startswith("BBU_")]
    bbb_c = [c for c in cols if c.startswith("BBB_")]
    bbp_c = [c for c in cols if c.startswith("BBP_")]
    if not lower_c or not mid_c or not upper_c:
        return {"error": "数据不足"}
    upper = float(row[upper_c[0]])
    middle = float(row[mid_c[0]])
    lower = float(row[lower_c[0]])
    bandwidth = float(row[bbb_c[0]]) if bbb_c else (
        (upper - lower) / middle * 100 if middle else 0.0
    )
    percent_b = float(row[bbp_c[0]]) if bbp_c else (
        (float(close.iloc[-1]) - lower) / (upper - lower) if upper != lower else 0.5
    )
    current = float(close.iloc[-1])
    sig, sug = _bollinger_signal_text(current, upper, lower, percent_b)
    return {
        "upper": round(upper, 4),
        "middle": round(middle, 4),
        "lower": round(lower, 4),
        "bandwidth": round(bandwidth, 2),
        "percent_b": round(percent_b, 4),
        "signal": sig,
        "suggestion": sug,
    }


def _standard_kdj(high: Any, low: Any, close: Any, cfg: Dict[str, Any]) -> Dict[str, Any]:
    kcfg = cfg["kdj"]
    # pandas_ta：length=RSV 周期，signal=K/D 平滑（常用 9,3 对应国内 KDJ(9,3,3) 的主参数）
    kdf = pta.kdj(
        high=high,
        low=low,
        close=close,
        length=kcfg["fast_k"],
        signal=kcfg["slow_k"],
    )
    if kdf is None or kdf.empty:
        return {"error": "数据不足"}
    cols = kdf.columns.tolist()
    kc = [c for c in cols if c.startswith("K_")]
    dc = [c for c in cols if c.startswith("D_")]
    jc = [c for c in cols if c.startswith("J_")]
    if not kc or not dc or not jc:
        return {"error": "数据不足"}
    kv = _last_valid(kdf[kc[0]])
    dv = _last_valid(kdf[dc[0]])
    jv = _last_valid(kdf[jc[0]])
    if kv is None or dv is None or jv is None:
        return {"error": "数据不足"}

    sig = "中性"
    k_prev = kdf[kc[0]].dropna()
    d_prev = kdf[dc[0]].dropna()
    if len(k_prev) >= 2 and len(d_prev) >= 2:
        if float(k_prev.iloc[-2]) <= float(d_prev.iloc[-2]) and kv > dv:
            sig = "金叉"
        elif float(k_prev.iloc[-2]) >= float(d_prev.iloc[-2]) and kv < dv:
            sig = "死叉"
    if sig == "中性":
        if kv > 80 and dv > 80:
            sig = "超买"
        elif kv < 20 and dv < 20:
            sig = "超卖"

    return {
        "k": round(kv, 2),
        "d": round(dv, 2),
        "j": round(jv, 2),
        "signal": sig,
    }


def _standard_cci(high: Any, low: Any, close: Any, cfg: Dict[str, Any]) -> Dict[str, Any]:
    length = cfg["cci"]["length"]
    cci_s = pta.cci(high=high, low=low, close=close, length=length)
    v = _last_valid(cci_s)
    if v is None:
        return {"error": "数据不足", "length": length}
    if v > 100:
        sig = "强势"
    elif v < -100:
        sig = "弱势"
    else:
        sig = "中性"
    return {"cci": round(v, 2), "length": length, "signal": sig}


def _standard_adx(high: Any, low: Any, close: Any, cfg: Dict[str, Any]) -> Dict[str, Any]:
    length = cfg["adx"]["length"]
    adx_df = pta.adx(high=high, low=low, close=close, length=length)
    if adx_df is None or adx_df.empty:
        return {"error": "数据不足", "length": length}
    cols = adx_df.columns.tolist()
    ac = [c for c in cols if c.startswith("ADX_")]
    if not ac:
        return {"error": "数据不足", "length": length}
    v = _last_valid(adx_df[ac[0]])
    if v is None:
        return {"error": "数据不足", "length": length}
    if v > 25:
        sig = "趋势较强"
    elif v < 20:
        sig = "趋势较弱"
    else:
        sig = "中性"
    return {"adx": round(v, 2), "length": length, "signal": sig}


def _standard_atr(high: Any, low: Any, close: Any, cfg: Dict[str, Any]) -> Dict[str, Any]:
    length = cfg["atr"]["length"]
    atr_s = pta.atr(high=high, low=low, close=close, length=length)
    v = _last_valid(atr_s)
    if v is None:
        return {"error": "数据不足", "period": length}
    return {"atr": round(v, 4), "period": length}


def _compute_standard(
    close: Any,
    high: Any,
    low: Any,
    indicators: List[str],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    if not PANDAS_TA_AVAILABLE or pta is None:
        raise RuntimeError("pandas_ta 未安装")
    out: Dict[str, Any] = {}
    if "ma" in indicators:
        out["ma"] = _standard_ma(close, cfg)
    if "macd" in indicators:
        out["macd"] = _standard_macd(close, cfg)
    if "rsi" in indicators:
        out["rsi"] = _standard_rsi(close, cfg)
    if "bollinger" in indicators:
        out["bollinger"] = _standard_bollinger(close, cfg)
    if "kdj" in indicators:
        out["kdj"] = _standard_kdj(high, low, close, cfg)
    if "cci" in indicators:
        out["cci"] = _standard_cci(high, low, close, cfg)
    if "adx" in indicators:
        out["adx"] = _standard_adx(high, low, close, cfg)
    if "atr" in indicators:
        out["atr"] = _standard_atr(high, low, close, cfg)
    return out


def _calculate_ma(closes: List[float]) -> Dict:
    """计算移动平均线（legacy Coze 逻辑，周期固定 5/10/20/60）"""
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else None

    current = closes[-1]

    if ma5 > ma10 > ma20:
        arrangement = "多头排列"
    elif ma5 < ma10 < ma20:
        arrangement = "空头排列"
    else:
        arrangement = "交叉震荡"

    if len(closes) >= 6:
        prev_ma5 = sum(closes[-6:-1]) / 5
        prev_ma10 = sum(closes[-11:-1]) / 10

        if prev_ma5 <= prev_ma10 and ma5 > ma10:
            cross = "金叉"
        elif prev_ma5 >= prev_ma10 and ma5 < ma10:
            cross = "死叉"
        else:
            cross = "无"
    else:
        cross = "数据不足"

    return {
        "ma5": round(ma5, 4),
        "ma10": round(ma10, 4),
        "ma20": round(ma20, 4),
        "ma60": round(ma60, 4) if ma60 else None,
        "arrangement": arrangement,
        "cross_signal": cross,
        "price_vs_ma20": round((current / ma20 - 1) * 100, 2),
        "price_vs_ref_period": 20,
        "periods": [5, 10, 20, 60],
    }


def _calculate_macd(closes: List[float]) -> Dict:
    """计算MACD指标（legacy Coze 逻辑；柱为 2*(DIF-DEA)）"""

    def ema(data, period):
        multiplier = 2 / (period + 1)
        ema_values = [data[0]]
        for price in data[1:]:
            ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
        return ema_values

    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)

    dif = [ema12[i] - ema26[i] for i in range(len(closes))]
    dea = ema(dif, 9)
    macd_hist = [(dif[i] - dea[i]) * 2 for i in range(len(closes))]

    current_dif = dif[-1]
    current_dea = dea[-1]
    current_macd = macd_hist[-1]

    if len(dif) >= 2:
        if dif[-2] <= dea[-2] and current_dif > current_dea:
            signal = "金叉"
        elif dif[-2] >= dea[-2] and current_dif < current_dea:
            signal = "死叉"
        elif current_macd > 0 and macd_hist[-2] < current_macd:
            signal = "红柱放大"
        elif current_macd < 0 and macd_hist[-2] > current_macd:
            signal = "绿柱放大"
        else:
            signal = "无明显信号"
    else:
        signal = "数据不足"

    return {
        "dif": round(current_dif, 4),
        "dea": round(current_dea, 4),
        "macd": round(current_macd, 4),
        "signal": signal,
    }


def _calculate_rsi(closes: List[float], period: int = 14) -> Dict:
    """计算RSI（legacy：最近 N 期涨跌简单平均，非 Wilder）"""
    gains = []
    losses = []

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    if len(gains) < period:
        return {"error": "数据不足"}

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        rsi = 100
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

    if rsi > 80:
        signal = "超买"
        suggestion = "可能回调"
    elif rsi > 70:
        signal = "偏强"
        suggestion = "注意风险"
    elif rsi < 20:
        signal = "超卖"
        suggestion = "可能反弹"
    elif rsi < 30:
        signal = "偏弱"
        suggestion = "观察企稳"
    else:
        signal = "中性"
        suggestion = "正常区间"

    return {
        "rsi": round(rsi, 2),
        "period": period,
        "signal": signal,
        "suggestion": suggestion,
    }


def _calculate_bollinger(closes: List[float], period: int = 20, std_dev: float = 2) -> Dict:
    """计算布林带（legacy Coze 逻辑）"""
    if len(closes) < period:
        return {"error": "数据不足"}

    middle = sum(closes[-period:]) / period

    variance = sum((p - middle) ** 2 for p in closes[-period:]) / period
    std = math.sqrt(variance)

    upper = middle + std_dev * std
    lower = middle - std_dev * std

    current = closes[-1]

    bandwidth = (upper - lower) / middle * 100

    if upper != lower:
        percent_b = (current - lower) / (upper - lower)
    else:
        percent_b = 0.5

    if current > upper:
        signal = "突破上轨"
        suggestion = "可能超买或突破"
    elif current < lower:
        signal = "突破下轨"
        suggestion = "可能超卖或破位"
    elif percent_b > 0.8:
        signal = "接近上轨"
        suggestion = "注意压力"
    elif percent_b < 0.2:
        signal = "接近下轨"
        suggestion = "注意支撑"
    else:
        signal = "区间内"
        suggestion = "正常波动"

    return {
        "upper": round(upper, 4),
        "middle": round(middle, 4),
        "lower": round(lower, 4),
        "bandwidth": round(bandwidth, 2),
        "percent_b": round(percent_b, 4),
        "signal": signal,
        "suggestion": suggestion,
    }


def _compute_legacy(closes: List[float], indicators: List[str], cfg: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if "ma" in indicators:
        out["ma"] = _calculate_ma(closes)
    if "macd" in indicators:
        out["macd"] = _calculate_macd(closes)
    if "rsi" in indicators:
        out["rsi"] = _calculate_rsi(closes, period=cfg["rsi"]["length"])
    if "bollinger" in indicators:
        b = cfg["bollinger"]
        out["bollinger"] = _calculate_bollinger(closes, period=b["length"], std_dev=b["std"])
    if "kdj" in indicators or "cci" in indicators or "adx" in indicators or "atr" in indicators:
        logger.warning("legacy 引擎不支持 kdj/cci/adx/atr，已跳过；请使用 engine=standard")
    return out


def _adapt_data_collection_output(price_data: Any, logger=None) -> List[Dict]:
    """适配数据采集插件的输出格式"""
    if isinstance(price_data, dict):
        if 'data' in price_data:
            data = price_data['data']
            if isinstance(data, dict) and 'klines' in data:
                return data['klines']
            elif isinstance(data, list):
                return data
        elif 'klines' in price_data:
            return price_data['klines']

    if isinstance(price_data, list):
        return price_data

    return []


@cache_result(cache_type="result", ttl=300)
def calculate_technical_indicators(
    symbol: str = "510300",
    data_type: str = "etf_daily",
    period: Optional[str] = None,
    indicators: List[str] = None,
    lookback_days: int = 120,
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None,
    klines_data: Optional[List[Dict[str, Any]]] = None,
    engine: Optional[str] = None,
    timeframe_minutes: Optional[int] = None,
    ma_periods: Optional[List[int]] = None,
    rsi_length: Optional[int] = None,
) -> Dict[str, Any]:
    """
    计算技术指标。

    engine:
        None — 使用合并后配置 `technical_indicators.engine`（默认 standard；来源：`config/domains/analytics.yaml`）
        standard — pandas_ta 向量化（Wilder RSI 等）
        legacy — 原 Coze 列表实现（与旧版数值一致；不含 kdj/cci/adx/atr）
    timeframe_minutes:
        若 >=2，在分钟数据上将 K 线聚合为该周期（如 5m 源数据 -> 30m）后再算指标。
    ma_periods / rsi_length:
        单次调用覆盖合并后配置中的均线周期与 RSI 长度（如日内监控 MA10/20 + RSI14）。
    """
    try:
        from datetime import datetime, timedelta

        cfg = _load_technical_indicators_config()
        eff_engine = (engine or cfg.get("engine") or "standard").strip().lower()
        if eff_engine not in ("standard", "legacy"):
            eff_engine = "standard"

        sh_ma: List[int] = []
        sh_rsi: Optional[int] = None
        if indicators is not None:
            sh_ma, sh_rsi = _extract_shorthand_ma_rsi_periods(indicators)
            indicators_eff = _normalize_indicator_names(indicators)
            if sh_ma and "ma" not in indicators_eff:
                indicators_eff.append("ma")
            if sh_rsi is not None and "rsi" not in indicators_eff:
                indicators_eff.append("rsi")
            if not indicators_eff:
                indicators_eff = list(
                    cfg.get("default_indicators") or ["ma", "macd", "rsi", "bollinger"]
                )
        else:
            indicators_eff = list(
                cfg.get("default_indicators") or ["ma", "macd", "rsi", "bollinger"]
            )

        ma_use = ma_periods if ma_periods else (sh_ma if sh_ma else None)
        rsi_use = rsi_length if rsi_length is not None else sh_rsi
        cfg_run = _merge_runtime_config(cfg, ma_use, rsi_use)

        notes_pre: List[str] = []
        if eff_engine == "legacy" and (
            (timeframe_minutes is not None and int(timeframe_minutes) >= 2) or ma_use is not None
        ):
            eff_engine = "standard"
            notes_pre.append("重采样或自定义 ma_periods 需 standard 引擎，已切换")

        import pandas as pd

        df = None

        if klines_data and isinstance(klines_data, list) and len(klines_data) > 0:
            try:
                df = pd.DataFrame(klines_data)
                col_map = {'开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume'}
                for cn, en in col_map.items():
                    if cn in df.columns and en not in df.columns:
                        df[en] = df[cn]
                if 'close' not in df.columns and '收盘' in df.columns:
                    df['close'] = df['收盘']
            except Exception as e:
                logger.debug(f"klines_data 转换失败，回退缓存读取: {e}", exc_info=True)

        if df is None or df.empty:
            import pytz

            tz_shanghai = pytz.timezone('Asia/Shanghai')
            now = datetime.now(tz_shanghai)
            end_date = now.strftime('%Y%m%d')
            if data_type in ['etf_minute', 'index_minute']:
                start_date = (now - timedelta(days=lookback_days * 2)).strftime('%Y%m%d')
            else:
                start_date = (now - timedelta(days=lookback_days)).strftime('%Y%m%d')

            cache_read = read_cache_data(
                data_type=data_type,
                symbol=symbol,
                period=period,
                start_date=start_date,
                end_date=end_date,
                return_df=True,
            )

            if cache_read.get('df') is not None and not cache_read['df'].empty:
                df = cache_read['df']
            elif not cache_read.get('success', False):
                return {
                    'success': False,
                    'message': f"Failed to load data from cache: {cache_read.get('message', 'Unknown error')}",
                    'data': None
                }
            else:
                return {
                    'success': False,
                    'message': 'Failed to load data from cache: No data available',
                    'data': None
                }

        df = _normalize_ohlcv_dataframe(df)
        tfm = int(timeframe_minutes) if timeframe_minutes is not None else 0
        if tfm >= 2:
            df = _resample_minute_ohlcv(df, tfm)
        close, high, low, _vol = _extract_ohlcv_series(df)
        closes_list = close.dropna().tolist()
        min_need = _min_bars_required(indicators_eff, cfg_run)
        if len(closes_list) < min_need:
            return {
                'success': False,
                'message': f'数据不足: {len(closes_list)} < {min_need}（当前所选指标至少需要 {min_need} 条收盘价）',
                'data': None
            }

        notes: List[str] = list(notes_pre)
        if eff_engine == "standard" and not PANDAS_TA_AVAILABLE:
            if tfm >= 2 or ma_use is not None:
                return {
                    "success": False,
                    "message": (
                        "未安装 pandas-ta：timeframe_minutes 重采样或自定义 ma_periods/扩展指标（kdj 等）"
                        "需要 standard 引擎。请执行 pip install -r requirements.txt"
                    ),
                    "data": None,
                }
            logger.warning("pandas_ta 未安装，回退 legacy 计算")
            notes.append("pandas_ta 未安装，已回退 legacy 引擎")
            eff_engine = "legacy"

        result_data: Dict[str, Any] = {
            "symbol": symbol,
            "current_price": closes_list[-1],
            "indicators": {},
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "engine": eff_engine,
        }
        if tfm >= 2:
            result_data["timeframe_minutes"] = tfm
        if ma_use:
            result_data["ma_periods_effective"] = list(cfg_run["ma_periods"])
        if rsi_use is not None:
            result_data["rsi_length_effective"] = int(cfg_run["rsi"]["length"])
        if notes:
            result_data["notes"] = notes

        if eff_engine == "standard":
            try:
                result_data["indicators"] = _compute_standard(
                    close, high, low, indicators_eff, cfg_run
                )
            except Exception as e:
                logger.warning("standard 引擎失败，回退 legacy: %s", e)
                result_data["engine"] = "legacy"
                result_data.setdefault("notes", []).append(f"standard 引擎失败已回退: {e}")
                result_data["indicators"] = _compute_legacy(closes_list, indicators_eff, cfg_run)
        else:
            result_data["indicators"] = _compute_legacy(closes_list, indicators_eff, cfg_run)

        result_data["signal"] = _generate_signal(result_data["indicators"])

        if not df.empty and '日期' in df.columns:
            start_d = df['日期'].iloc[0]
            end_d = df['日期'].iloc[-1]
            data_count = len(df)
            result_data["data_range"] = f"{start_d} 至 {end_d} ({data_count} 个交易日)"
        elif not df.empty and 'date' in df.columns:
            start_d = df['date'].iloc[0]
            end_d = df['date'].iloc[-1]
            data_count = len(df)
            result_data["data_range"] = f"{start_d} 至 {end_d} ({data_count} 个交易日)"
        elif not df.empty:
            for tc in ("time", "datetime", "trade_date"):
                if tc in df.columns:
                    start_d = df[tc].iloc[0]
                    end_d = df[tc].iloc[-1]
                    result_data["data_range"] = f"{start_d} 至 {end_d} ({len(df)} 条)"
                    break
            if "data_range" not in result_data and len(df.columns) > 0:
                c0 = df.columns[0]
                if c0 not in ("open", "high", "low", "close", "volume"):
                    start_d = df[c0].iloc[0]
                    end_d = df[c0].iloc[-1]
                    result_data["data_range"] = f"{start_d} 至 {end_d} ({len(df)} 条)"

        formatted_message = _format_indicators_message(result_data)

        return {
            "success": True,
            "data": result_data,
            "message": formatted_message,
            "source": "calculated"
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"计算技术指标失败: {str(e)}",
            "data": None
        }


def _generate_signal(indicators: Dict) -> Dict:
    """生成综合信号"""
    signals = []

    if "ma" in indicators:
        ma = indicators["ma"]
        if ma.get("cross_signal") == "金叉":
            signals.append("均线金叉")
        elif ma.get("cross_signal") == "死叉":
            signals.append("均线死叉")
        if ma.get("arrangement") == "多头排列":
            signals.append("多头排列")
        elif ma.get("arrangement") == "空头排列":
            signals.append("空头排列")

    if "macd" in indicators:
        macd = indicators["macd"]
        sig = macd.get("signal", "")
        if "金叉" in sig:
            signals.append("MACD金叉")
        elif "死叉" in sig:
            signals.append("MACD死叉")

    if "rsi" in indicators:
        rsi = indicators["rsi"]
        if rsi.get("error"):
            pass
        else:
            sig = rsi.get("signal", "")
            if "超买" in sig:
                signals.append("RSI超买")
            elif "超卖" in sig:
                signals.append("RSI超卖")

    if "bollinger" in indicators:
        boll = indicators["bollinger"]
        if not boll.get("error"):
            sig = boll.get("signal", "")
            if "突破上轨" in sig:
                signals.append("突破布林上轨")
            elif "突破下轨" in sig:
                signals.append("突破布林下轨")

    if "kdj" in indicators:
        kd = indicators["kdj"]
        if not kd.get("error"):
            sig = kd.get("signal", "")
            if sig == "超买":
                signals.append("KDJ超买")
            elif sig == "超卖":
                signals.append("KDJ超卖")
            elif sig == "金叉":
                signals.append("KDJ金叉")
            elif sig == "死叉":
                signals.append("KDJ死叉")

    if "cci" in indicators:
        cc = indicators["cci"]
        if not cc.get("error"):
            if cc.get("signal") == "强势":
                signals.append("CCI强势")
            elif cc.get("signal") == "弱势":
                signals.append("CCI弱势")

    if "adx" in indicators:
        ad = indicators["adx"]
        if not ad.get("error") and ad.get("signal") == "趋势较强":
            signals.append("ADX趋势较强")

    return {
        "signals": signals,
        "summary": ", ".join(signals) if signals else "无明显信号"
    }


def _format_indicators_message(result_data: Dict[str, Any]) -> str:
    """格式化技术指标结果为易读的消息"""
    if not result_data:
        return "数据为空"

    symbol = result_data.get("symbol", "N/A")
    current_price = result_data.get("current_price", 0)
    indicators = result_data.get("indicators", {})
    signal = result_data.get("signal", {})
    timestamp = result_data.get("timestamp", "")
    engine = result_data.get("engine", "")

    data_range = ""
    if "data_range" in result_data:
        data_range = f"\n数据范围: {result_data['data_range']}"

    notes = result_data.get("notes") or []
    note_txt = ""
    if notes:
        note_txt = "\n⚠️ " + "；".join(notes) + "\n"

    eng_line = f"\n计算引擎: {engine}" if engine else ""

    message = f"✅ 技术指标计算完成 - {symbol} ETF{eng_line}\n"
    message += f"当前价格: {current_price:.3f}\n"
    if note_txt:
        message += note_txt
    if data_range:
        message += data_range

    message += "\n📊 技术指标详情:\n"

    if "rsi" in indicators:
        rsi_data = indicators["rsi"]
        if rsi_data.get("error"):
            message += f"\n⚠️ RSI: {rsi_data.get('error')}\n"
        else:
            rsi_value = rsi_data.get("rsi", "N/A")
            rsi_signal = rsi_data.get("signal", "N/A")
            rsi_suggestion = rsi_data.get("suggestion", "")
            message += "\n✅ RSI (相对强弱指标):\n"
            message += f"   RSI值: {rsi_value}\n"
            message += f"   状态: {rsi_signal}"
            if rsi_suggestion:
                message += f" ({rsi_suggestion})"
            message += "\n"

    if "macd" in indicators:
        macd_data = indicators["macd"]
        dif = macd_data.get("dif", "N/A")
        dea = macd_data.get("dea", "N/A")
        macd_value = macd_data.get("macd", "N/A")
        macd_signal = macd_data.get("signal", "N/A")
        message += "\n✅ MACD (移动平均收敛发散):\n"
        message += f"   DIF: {dif}\n"
        message += f"   DEA: {dea}\n"
        message += f"   MACD柱: {macd_value}\n"
        message += f"   信号: {macd_signal}\n"

    if "ma" in indicators:
        ma_raw = indicators["ma"]
        message += "\n✅ MA (移动平均线):\n"
        periods = sorted(ma_raw.get("periods", [5, 10, 20, 60]))
        for p in periods:
            key = f"ma{p}"
            if key in ma_raw and ma_raw[key] is not None:
                message += f"   MA{p}: {ma_raw[key]}\n"
        for key in ("ma5", "ma10", "ma20", "ma60"):
            if key in ma_raw and key not in {f"ma{p}" for p in periods}:
                message += f"   {key.upper()}: {ma_raw.get(key)}\n"
        arrangement = ma_raw.get("arrangement", "N/A")
        cross_signal = ma_raw.get("cross_signal", "N/A")
        price_vs_ma20 = ma_raw.get("price_vs_ma20", "N/A")
        ref_p = ma_raw.get("price_vs_ref_period", 20)
        message += f"   均线排列: {arrangement}\n"
        message += f"   交叉信号: {cross_signal}\n"
        if price_vs_ma20 != "N/A" and price_vs_ma20 is not None:
            message += f"   价格相对MA{ref_p}: {price_vs_ma20}%\n"

    if "kdj" in indicators:
        kd = indicators["kdj"]
        if kd.get("error"):
            message += f"\n⚠️ KDJ: {kd.get('error')}\n"
        else:
            message += "\n✅ KDJ:\n"
            message += f"   K: {kd.get('k', 'N/A')}  D: {kd.get('d', 'N/A')}  J: {kd.get('j', 'N/A')}\n"
            message += f"   信号: {kd.get('signal', 'N/A')}\n"

    if "cci" in indicators:
        cc = indicators["cci"]
        if cc.get("error"):
            message += f"\n⚠️ CCI: {cc.get('error')}\n"
        else:
            message += "\n✅ CCI:\n"
            message += f"   CCI: {cc.get('cci', 'N/A')}  状态: {cc.get('signal', 'N/A')}\n"

    if "adx" in indicators:
        ad = indicators["adx"]
        if ad.get("error"):
            message += f"\n⚠️ ADX: {ad.get('error')}\n"
        else:
            message += "\n✅ ADX:\n"
            message += f"   ADX: {ad.get('adx', 'N/A')}  状态: {ad.get('signal', 'N/A')}\n"

    if "atr" in indicators:
        at = indicators["atr"]
        if at.get("error"):
            message += f"\n⚠️ ATR: {at.get('error')}\n"
        else:
            message += "\n✅ ATR (平均真实波动幅度):\n"
            message += f"   ATR值: {at.get('atr', 'N/A')}\n"

    if "bollinger" in indicators:
        boll_data = indicators["bollinger"]
        if boll_data.get("error"):
            message += f"\n⚠️ BOLL: {boll_data.get('error')}\n"
        else:
            upper = boll_data.get("upper", "N/A")
            middle = boll_data.get("middle", "N/A")
            lower = boll_data.get("lower", "N/A")
            bandwidth = boll_data.get("bandwidth", "N/A")
            percent_b = boll_data.get("percent_b", "N/A")
            boll_signal = boll_data.get("signal", "N/A")
            boll_suggestion = boll_data.get("suggestion", "")
            message += "\n✅ BOLL (布林带):\n"
            message += f"   上轨: {upper}\n"
            message += f"   中轨: {middle}\n"
            message += f"   下轨: {lower}\n"
            message += f"   带宽: {bandwidth}%\n"
            message += f"   %B: {percent_b}\n"
            message += f"   信号: {boll_signal}"
            if boll_suggestion:
                message += f" ({boll_suggestion})"
            message += "\n"

    if signal:
        signal_summary = signal.get("summary", "无明显信号")
        message += f"\n📈 综合信号: {signal_summary}\n"

    if timestamp:
        message += f"\n⏰ 计算时间: {timestamp}\n"

    return message


def tool_calculate_technical_indicators(
    symbol: str = "510300",
    data_type: str = "etf_daily",
    period: Optional[str] = None,
    indicators: Optional[List[str]] = None,
    lookback_days: int = 120,
    klines_data: Optional[List[Dict[str, Any]]] = None,
    engine: Optional[str] = None,
    timeframe_minutes: Optional[int] = None,
    ma_periods: Optional[List[int]] = None,
    rsi_length: Optional[int] = None,
) -> Dict[str, Any]:
    """OpenClaw 工具：计算技术指标。engine=legacy 与历史数值一致；standard（默认）使用 pandas_ta。"""
    result = calculate_technical_indicators(
        symbol=symbol,
        data_type=data_type,
        period=period,
        indicators=indicators,
        lookback_days=lookback_days,
        klines_data=klines_data,
        engine=engine,
        timeframe_minutes=timeframe_minutes,
        ma_periods=ma_periods,
        rsi_length=rsi_length,
    )

    if result.get("success") and result.get("message"):
        return result
    if result.get("success") and result.get("data"):
        formatted_message = _format_indicators_message(result.get("data"))
        result["message"] = formatted_message
        return result
    return result
