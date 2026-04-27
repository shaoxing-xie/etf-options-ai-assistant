"""
Utility to temporarily disable proxy environment variables.

Some market data sources may be blocked when requests are forced through a corporate proxy
(e.g. 403 Tunnel connection failed). For those calls, we explicitly bypass proxy env vars.
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from typing import Any, Dict, Iterator, Optional

_PROXY_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


@contextmanager
def without_proxy_env(no_proxy_value: str = "*") -> Iterator[None]:
    """
    Temporarily unset proxy-related environment variables for the current process.
    """
    import os

    backup: Dict[str, Optional[str]] = {}
    for k in _PROXY_KEYS:
        backup[k] = os.environ.get(k)

    try:
        # Unset proxy vars
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            if k in os.environ:
                os.environ.pop(k, None)
        # Force bypass
        os.environ["NO_PROXY"] = no_proxy_value
        os.environ["no_proxy"] = no_proxy_value
        yield
    finally:
        for k, v in backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextmanager
def with_proxy_env(proxy_url: str) -> Iterator[None]:
    """
    Temporarily set HTTP(S)/ALL proxy vars for the current process.
    """
    import os

    proxy = str(proxy_url or "").strip()
    backup: Dict[str, Optional[str]] = {k: os.environ.get(k) for k in _PROXY_KEYS}
    try:
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            os.environ[k] = proxy
        # Let caller/network stack decide no_proxy behavior; do not force override.
        yield
    finally:
        for k, v in backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def resolve_proxy_url(config: Dict[str, Any], source_name: str) -> str:
    """
    Resolve proxy URL for a specific source from market_data config:
      network.proxy.default
      network.proxy.per_source.<source_name>
    """
    cfg = config if isinstance(config, dict) else {}
    net = cfg.get("network") if isinstance(cfg.get("network"), dict) else {}
    px = net.get("proxy") if isinstance(net.get("proxy"), dict) else {}

    default_cfg = px.get("default") if isinstance(px.get("default"), dict) else {}
    per_source = px.get("per_source") if isinstance(px.get("per_source"), dict) else {}
    src_cfg = per_source.get(str(source_name)) if isinstance(per_source.get(str(source_name)), dict) else {}

    if src_cfg:
        if not bool(src_cfg.get("enabled", False)):
            return ""
        return str(src_cfg.get("url") or "").strip()

    if not bool(default_cfg.get("enabled", False)):
        return ""
    return str(default_cfg.get("url") or "").strip()


def proxy_env_for_source(config: Dict[str, Any], source_name: str):
    """
    Return a context manager that enables proxy only for the target source.
    If no proxy is configured, returns a no-op context manager.
    """
    proxy_url = resolve_proxy_url(config, source_name)
    if proxy_url:
        return with_proxy_env(proxy_url)
    return nullcontext()


# Historical name used in early chart_console wiring; prefer `proxy_env_for_source`.
proxy_context_for_source = proxy_env_for_source

