"""统一数据采集编排入口（薄封装）：复用 tool_run_data_cache_job / 核心采集逻辑。"""

from __future__ import annotations

from typing import Any, Dict


def orchestrator_run_data_pipeline(
    job: str,
    *,
    throttle_stock: bool = False,
    notify: bool = False,
) -> Dict[str, Any]:
    from data_collection.run_data_cache_job import tool_run_data_cache_job

    return tool_run_data_cache_job(
        str(job or "").strip(),
        throttle_stock=throttle_stock,
        notify=notify,
    )
