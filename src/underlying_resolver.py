"""
标的解析：将用户输入（代码/简称）解析为 6 位证券代码 + 资产类别（指数/ETF/A 股）。

规则：
- 支持显式类别前缀：指数:/ETF:/股票:（及常见别名），优先级最高。
- 无类别时：纯 6 位数字按代码段规则唯一归类；无法归类则报错并要求加前缀。
- 按名称解析时：全市场精确匹配唯一则采纳；否则若模糊匹配多条则返回歧义错误。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

AssetType = str  # "index" | "etf" | "stock"

_PREFIX_MAP: Tuple[Tuple[str, AssetType], ...] = (
    ("指数:", "index"),
    ("INDEX:", "index"),
    ("IDX:", "index"),
    ("ETF:", "etf"),
    ("股票:", "stock"),
    ("A股:", "stock"),
    ("STOCK:", "stock"),
    ("个股:", "stock"),
)


def _strip_asset_prefix(raw: str) -> Tuple[str, Optional[AssetType]]:
    s = str(raw or "").strip()
    if not s:
        return "", None
    sl = s.lower()
    for pref, atype in _PREFIX_MAP:
        pl = pref.lower()
        if sl.startswith(pl):
            return s[len(pref) :].strip(), atype
    return s, None


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", "", str(s or "")).replace("　", "").lower()


def _extract_six_digit(code_cell: str) -> Optional[str]:
    m = re.search(r"(\d{6})", str(code_cell or ""))
    return m.group(1) if m else None


def _classify_six_digit(code: str) -> Optional[AssetType]:
    """无显式类别时，由 6 位代码唯一推断类别；无法推断则返回 None。"""
    if not re.fullmatch(r"\d{6}", code):
        return None
    if code.startswith(("51", "15", "16")):
        return "etf"
    if code in {"000001", "000016", "000300", "000905"} or code.startswith("399"):
        return "index"
    if code.startswith(
        ("000", "001", "002", "003", "300", "301", "600", "601", "603", "605", "688")
    ):
        return "stock"
    return None


def _scan_exact_name(
    qn: str, df: Any, asset_type: AssetType, matches: List[Tuple[str, AssetType, str]]
) -> None:
    if df is None or getattr(df, "empty", True):
        return
    code_col = next((c for c in ["代码", "code", "symbol"] if c in df.columns), None)
    name_col = next((c for c in ["名称", "name"] if c in df.columns), None)
    if not code_col or not name_col:
        return
    for _, row in df.iterrows():
        name = str(row.get(name_col, "") or "")
        if _norm_name(name) != qn:
            continue
        code = _extract_six_digit(str(row.get(code_col, "")))
        if code:
            matches.append((code, asset_type, name))


def _scan_substring_name(
    qn: str, df: Any, asset_type: AssetType, matches: List[Tuple[str, AssetType, str]]
) -> None:
    if df is None or getattr(df, "empty", True) or len(qn) < 2:
        return
    code_col = next((c for c in ["代码", "code", "symbol"] if c in df.columns), None)
    name_col = next((c for c in ["名称", "name"] if c in df.columns), None)
    if not code_col or not name_col:
        return
    for _, row in df.iterrows():
        name = str(row.get(name_col, "") or "")
        nn = _norm_name(name)
        if not nn:
            continue
        if qn not in nn:
            continue
        code = _extract_six_digit(str(row.get(code_col, "")))
        if code:
            matches.append((code, asset_type, name))


def _dedupe(tuples: List[Tuple[str, AssetType, str]]) -> List[Tuple[str, AssetType, str]]:
    seen = set()
    out: List[Tuple[str, AssetType, str]] = []
    for code, atype, label in tuples:
        key = (code, atype)
        if key in seen:
            continue
        seen.add(key)
        out.append((code, atype, label))
    return out


@dataclass
class UnderlyingResolveResult:
    ok: bool
    code: str = ""
    asset_type: str = ""
    error: str = ""
    candidates: List[Dict[str, str]] = field(default_factory=list)


def resolve_volatility_underlying(
    raw_input: str,
    asset_type_hint: Optional[str] = None,
) -> UnderlyingResolveResult:
    """
    解析波动区间预测标的。

    asset_type_hint: 可选 "index" / "etf" / "stock"（小写），与前缀二选一即可。
    """
    body, prefix_type = _strip_asset_prefix(raw_input)
    hint = (asset_type_hint or "").strip().lower() or None
    if hint and hint not in ("index", "etf", "stock"):
        return UnderlyingResolveResult(
            ok=False,
            error=f"无效的 asset_type_hint: {asset_type_hint!r}，请使用 index / etf / stock。",
        )

    effective_type: Optional[AssetType] = prefix_type or hint
    compact = body.replace(" ", "")

    # 显式类别 + 6 位代码
    m = re.search(r"(\d{6})", compact)
    if m and effective_type:
        code = m.group(1)
        return UnderlyingResolveResult(ok=True, code=code, asset_type=effective_type)

    # 仅 6 位数字、无类别：按规则推断
    if re.fullmatch(r"\d{6}", compact) and not effective_type:
        inferred = _classify_six_digit(compact)
        if inferred:
            return UnderlyingResolveResult(ok=True, code=compact, asset_type=inferred)
        return UnderlyingResolveResult(
            ok=False,
            error=(
                f"无法根据代码 `{compact}` 唯一判断类别（指数/ETF/A股），"
                "请使用前缀指定，例如：指数:{compact}、ETF:{compact}、股票:{compact}。"
            ),
        )

    # 名称解析（无显式类别时必须能唯一确定）
    if not compact:
        return UnderlyingResolveResult(ok=False, error="标的输入为空。")

    qn = _norm_name(compact)
    try:
        import akshare as ak  # type: ignore
    except Exception as e:
        return UnderlyingResolveResult(
            ok=False, error=f"名称解析需要 akshare，导入失败: {e}"
        )

    exact: List[Tuple[str, AssetType, str]] = []
    try:
        _scan_exact_name(qn, ak.stock_zh_index_spot_sina(), "index", exact)
    except Exception:
        pass
    try:
        _scan_exact_name(qn, ak.fund_etf_spot_em(), "etf", exact)
    except Exception:
        pass
    try:
        _scan_exact_name(qn, ak.stock_zh_a_spot_em(), "stock", exact)
    except Exception:
        pass

    exact_u = _dedupe(exact)
    if effective_type:
        filtered = [t for t in exact_u if t[1] == effective_type]
        if len(filtered) == 1:
            c, t, lbl = filtered[0]
            return UnderlyingResolveResult(ok=True, code=c, asset_type=t)
        if len(filtered) > 1:
            return UnderlyingResolveResult(
                ok=False,
                error=f"在类别 `{effective_type}` 下名称 `{compact}` 匹配到多条记录，请改用 6 位代码。",
                candidates=[
                    {"code": x[0], "asset_type": x[1], "name": x[2]} for x in filtered
                ],
            )
    else:
        if len(exact_u) == 1:
            c, t, _ = exact_u[0]
            return UnderlyingResolveResult(ok=True, code=c, asset_type=t)
        if len(exact_u) > 1:
            return UnderlyingResolveResult(
                ok=False,
                error=(
                    f"名称 `{compact}` 在指数/ETF/A股中匹配到多条（请用前缀消歧），"
                    "例如：指数:沪深300、ETF:沪深300ETF。"
                ),
                candidates=[
                    {"code": x[0], "asset_type": x[1], "name": x[2]} for x in exact_u
                ],
            )

    # 子串匹配（无类别时仅当唯一）
    fuzzy: List[Tuple[str, AssetType, str]] = []
    try:
        _scan_substring_name(qn, ak.stock_zh_index_spot_sina(), "index", fuzzy)
    except Exception:
        pass
    try:
        _scan_substring_name(qn, ak.fund_etf_spot_em(), "etf", fuzzy)
    except Exception:
        pass
    try:
        _scan_substring_name(qn, ak.stock_zh_a_spot_em(), "stock", fuzzy)
    except Exception:
        pass

    fuzzy_u = _dedupe(fuzzy)
    if effective_type:
        fuzzy_u = [t for t in fuzzy_u if t[1] == effective_type]

    if len(fuzzy_u) == 1:
        c, t, _ = fuzzy_u[0]
        return UnderlyingResolveResult(ok=True, code=c, asset_type=t)
    if len(fuzzy_u) > 1:
        return UnderlyingResolveResult(
            ok=False,
            error=(
                f"名称 `{compact}` 匹配不唯一，请使用 6 位代码或加类别前缀"
                f"（指数:/ETF:/股票:）。候选："
                + "；".join(f"{x[2]}({x[0]},{x[1]})" for x in fuzzy_u[:8])
                + ("…" if len(fuzzy_u) > 8 else "")
            ),
            candidates=[
                {"code": x[0], "asset_type": x[1], "name": x[2]} for x in fuzzy_u[:20]
            ],
        )

    return UnderlyingResolveResult(
        ok=False,
        error=f"无法解析标的 `{raw_input}`：未找到匹配的指数/ETF/A股名称或代码。",
    )
