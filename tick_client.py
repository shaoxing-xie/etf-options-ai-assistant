"""
Tick 行情采集客户端封装（etf-options-ai-assistant）。

特性：
- 从项目根目录 `config.yaml` 的 `data_sources.tick` 段读取配置；
- 支持 iTick（免费环境/生产环境）Tick 拉取；
- 预留 Alltick（待按官方文档补齐）。

注意：
- 本实现遵循 iTick 文档中的认证方式：请求头 `token: <API_KEY>`。
  参考文档：https://docs.itick.org/en/rest-api/stocks/stock-tick
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.error import URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen


@dataclass
class TickConfig:
    primary: str
    secondary: Optional[str]
    symbols: Dict[str, Dict[str, Any]]
    providers: Dict[str, Dict[str, Any]]


def _load_yaml_config(path: str) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore[import]
    except Exception:
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _load_tick_config(config_path: str) -> Optional[TickConfig]:
    cfg = _load_yaml_config(config_path)
    data_sources = cfg.get("data_sources") or {}
    tick_cfg = data_sources.get("tick")
    if not isinstance(tick_cfg, dict):
        return None

    primary = str(tick_cfg.get("primary") or "").strip()
    if not primary:
        return None

    secondary = tick_cfg.get("secondary")
    if isinstance(secondary, str):
        secondary = secondary.strip() or None
    else:
        secondary = None

    symbols = tick_cfg.get("symbols") or {}
    providers = tick_cfg.get("providers") or {}

    return TickConfig(
        primary=primary,
        secondary=secondary,
        symbols=symbols,
        providers=providers,
    )


def _http_get_json(url: str, headers: Dict[str, str], timeout: float) -> Dict[str, Any]:
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def _itick_market_path(symbol_type: str) -> str:
    # iTick 使用 stock / indices / future / fund
    if symbol_type in {"indices", "index"}:
        return "indices"
    if symbol_type in {"future", "futures"}:
        return "future"
    if symbol_type in {"fund", "funds"}:
        return "fund"
    if symbol_type in {"etf"}:
        return "fund"
    return "stock"


def _build_itick_url(base_rest: str, market_path: str, endpoint: str, params: Dict[str, Any]) -> str:
    query = urlencode(params)
    return f"{base_rest.rstrip('/')}/{market_path}/{endpoint}?{query}"


def _fetch_itick_tick(
    provider_cfg: Dict[str, Any],
    logical_symbol: str,
    symbol_mapping: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    base_rest = str(provider_cfg.get("base_url_rest") or "").strip().rstrip("/")
    if not base_rest:
        return None, "missing_itick_base_url_rest"

    api_key = str(provider_cfg.get("api_key") or "").strip()
    if not api_key:
        return None, "missing_itick_api_key_in_config"

    timeout_ms = provider_cfg.get("timeout_ms", 2000)
    timeout = max(float(timeout_ms) / 1000.0, 0.5)

    mapped_code = symbol_mapping.get("itick")
    if not mapped_code:
        return None, "symbol_not_mapped_for_itick"

    # region：A 股 ETF 在上交所通常为 SH（深交所为 SZ）
    region = str(symbol_mapping.get("itick_region") or "SH").strip() or "SH"
    symbol_type = str(symbol_mapping.get("type") or "stock").strip() or "stock"
    market_path = _itick_market_path(symbol_type)

    code = mapped_code.split(".")[0] if "." in mapped_code else mapped_code

    headers = {
        "accept": "application/json",
        "token": api_key,
    }

    def call(market: str) -> Tuple[Optional[Dict[str, Any]], Optional[int], Optional[str]]:
        url = _build_itick_url(
            base_rest=base_rest,
            market_path=market,
            endpoint="tick",
            params={"region": region, "code": code},
        )
        try:
            t0 = time.time()
            raw = _http_get_json(url, headers=headers, timeout=timeout)
            latency_ms = int((time.time() - t0) * 1000)
            return raw, latency_ms, None
        except URLError as exc:
            return None, None, f"http_error:{exc}"
        except Exception as exc:  # noqa: BLE001
            return None, None, f"unexpected_error:{exc}"

    # ETF 优先走 fund，若 fund data=null 再尝试 stock（同样的 region/code）
    market_try_order = [market_path]
    if symbol_type in {"etf", "fund", "funds"} and market_path != "stock":
        market_try_order.append("stock")

    raw: Optional[Dict[str, Any]] = None
    latency_ms: Optional[int] = None
    last_err: Optional[str] = None
    for m in market_try_order:
        r, lat, err = call(m)
        if err:
            last_err = err
            continue
        if isinstance(r, dict) and r.get("data") is None:
            # iTick 在无权限/无该代码时可能返回 {"code":0,"msg":null,"data":null}
            last_err = "itick_data_null_or_not_entitled"
            raw = r
            latency_ms = lat
            continue
        raw = r
        latency_ms = lat
        last_err = None
        break

    if raw is None:
        return None, last_err or "itick_request_failed"

    # iTick 返回结构：{ code, msg, data: { s, ld, t, v, te } }
    data = raw.get("data") if isinstance(raw, dict) else None
    if data is None:
        return None, "itick_data_null_or_not_entitled"
    if not isinstance(data, dict):
        return None, "itick_response_missing_data"

    try:
        last = float(data.get("ld"))
        volume = float(data.get("v") or 0.0)
        ts = data.get("t")
    except Exception:  # noqa: BLE001
        return None, "parse_error"

    tick = {
        "symbol": logical_symbol,
        "provider": "itick",
        "last": last,
        "volume": volume,
        "timestamp": ts,
        "latency_ms": latency_ms,
        "raw": raw,
    }
    return tick, None


def _fetch_alltick_tick(
    provider_cfg: Dict[str, Any],
    logical_symbol: str,
    symbol_mapping: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Alltick REST 最新成交价（Latest Price）查询。

    文档：
    - GET /trade-tick
      https://en.apis.alltick.co/rest-api/http-interface-api/get-latest-transaction-price-query
    """
    base_rest = str(provider_cfg.get("base_url_rest") or "").strip().rstrip("/")
    if not base_rest:
        return None, "missing_alltick_base_url_rest"

    api_key = str(provider_cfg.get("api_key") or "").strip()
    if not api_key:
        return None, "missing_alltick_api_key_in_config"

    timeout_ms = provider_cfg.get("timeout_ms", 2000)
    timeout = max(float(timeout_ms) / 1000.0, 0.5)

    mapped_code = symbol_mapping.get("alltick")
    if not mapped_code:
        return None, "symbol_not_mapped_for_alltick"

    trace = f"tick_{logical_symbol}_{int(time.time()*1000)}"
    query_obj = {
        "trace": trace,
        "data": {"symbol_list": [{"code": mapped_code}]},
    }
    query_str = json.dumps(query_obj, separators=(",", ":"), ensure_ascii=False)
    url = f"{base_rest}/trade-tick?token={quote(api_key)}&query={quote(query_str)}"

    headers = {"Content-Type": "application/json"}

    try:
        t0 = time.time()
        raw = _http_get_json(url, headers=headers, timeout=timeout)
        latency_ms = int((time.time() - t0) * 1000)
    except URLError as exc:
        return None, f"http_error:{exc}"
    except Exception as exc:  # noqa: BLE001
        return None, f"unexpected_error:{exc}"

    # 预期结构：{ ret:200, msg, trace, data:{ tick_list:[{code, tick_time, price, volume,...}] } }
    if not isinstance(raw, dict):
        return None, "alltick_invalid_response"
    if int(raw.get("ret", 0)) != 200:
        return None, f"alltick_ret_not_200:{raw.get('ret')}:{raw.get('msg')}"

    data = raw.get("data")
    if not isinstance(data, dict):
        return None, "alltick_missing_data"
    tick_list = data.get("tick_list")
    if not isinstance(tick_list, list) or not tick_list:
        return None, "alltick_empty_tick_list"
    first = tick_list[0]
    if not isinstance(first, dict):
        return None, "alltick_tick_item_invalid"

    try:
        last = float(first.get("price"))
        volume = float(first.get("volume") or 0.0)
        ts = first.get("tick_time")
    except Exception:  # noqa: BLE001
        return None, "parse_error"

    tick = {
        "symbol": logical_symbol,
        "provider": "alltick",
        "last": last,
        "volume": volume,
        "timestamp": ts,
        "latency_ms": latency_ms,
        "raw": raw,
    }
    return tick, None


def get_best_tick(logical_symbol: str, config_path: str = "config.yaml") -> Dict[str, Any]:
    tick_cfg = _load_tick_config(config_path)
    if tick_cfg is None:
        return {"ok": False, "tick": None, "provider": None, "error": "tick_config_not_found_or_invalid"}

    symbol_mapping = tick_cfg.symbols.get(logical_symbol)
    if not isinstance(symbol_mapping, dict):
        return {"ok": False, "tick": None, "provider": None, "error": "symbol_not_configured_for_tick"}

    def try_provider(name: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        provider_cfg = tick_cfg.providers.get(name) or {}
        if not provider_cfg.get("enabled", False):
            return None, f"provider_{name}_disabled"
        if name == "itick":
            return _fetch_itick_tick(provider_cfg, logical_symbol, symbol_mapping)
        if name in {"alltick", "allticks"}:
            return _fetch_alltick_tick(provider_cfg, logical_symbol, symbol_mapping)
        return None, f"unknown_provider:{name}"

    tick, err = try_provider(tick_cfg.primary)
    if tick is not None:
        return {"ok": True, "tick": tick, "provider": tick["provider"], "error": None}

    if tick_cfg.secondary:
        tick2, err2 = try_provider(tick_cfg.secondary)
        if tick2 is not None:
            return {"ok": True, "tick": tick2, "provider": tick2["provider"], "error": None}
        return {"ok": False, "tick": None, "provider": None, "error": f"{err}; secondary_error:{err2}"}

    return {"ok": False, "tick": None, "provider": None, "error": err or "no_tick_provider"}


__all__ = ["get_best_tick"]

