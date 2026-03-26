"""
指数代码规范化（实时 / 日线 / 分钟线共用）。

- 工具层**不维护指数白名单**：任意合法 6 位代码均可进入查询，能否取数取决于各数据源。
- 统一为 6 位数字；新浪/东财等 symbol：**39xxxx → sz**，**其余 → sh**（与 Tushare 侧 ts_code 的 .SZ/.SH 推导一致）。
"""

from __future__ import annotations

from typing import Dict, Optional

# 常见指数中文名（仅展示用）
INDEX_KNOWN_NAMES: Dict[str, str] = {
    "000001": "上证指数",
    "399001": "深证成指",
    "399006": "创业板指",
    "000300": "沪深300",
    "000016": "上证50",
    "000905": "中证500",
    "000852": "中证1000",
}


def normalize_index_code_for_minute(raw: str) -> Optional[str]:
    """
    统一为 6 位数字指数代码（用于缓存键、mootdx symbol、与 sh/sz 推导）。
    支持：000300 / sh000300 / sz399001 / 000300.SH 等形式。
    无法解析则返回 None。
    """
    s = str(raw).strip()
    if not s:
        return None
    u = s.upper().replace("．", ".")
    for suf in (".SH", ".SZ"):
        if u.endswith(suf):
            u = u[: -len(suf)]
            break
    low = u.lower()
    if low.startswith("sh") and len(u) > 2:
        u = u[2:]
    elif low.startswith("sz") and len(u) > 2:
        u = u[2:]
    u = u.strip()
    if not u.isdigit():
        return None
    if len(u) != 6:
        return None
    return u


def index_sina_symbol(digits: str) -> str:
    """新浪 getKLineData / 东财等：深证 39xxxx -> sz，其余默认 sh。"""
    if digits.startswith("39"):
        return f"sz{digits}"
    return f"sh{digits}"


def index_display_name(digits: str) -> str:
    return INDEX_KNOWN_NAMES.get(digits, f"指数{digits}")


def tushare_index_ts_code(digits: str) -> str:
    """Tushare pro index_daily：深证 -> .SZ，其余 -> .SH。"""
    if digits.startswith("39"):
        return f"{digits}.SZ"
    return f"{digits}.SH"
