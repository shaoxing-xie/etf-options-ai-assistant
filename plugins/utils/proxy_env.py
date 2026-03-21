"""
Utility to temporarily disable proxy environment variables.

Some market data sources may be blocked when requests are forced through a corporate proxy
(e.g. 403 Tunnel connection failed). For those calls, we explicitly bypass proxy env vars.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Dict, Iterator, Optional

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

