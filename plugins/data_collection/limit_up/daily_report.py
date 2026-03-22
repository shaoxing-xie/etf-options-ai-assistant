"""
涨停回马枪盘后数据：涨停列表 + 板块热度 + 龙头识别，写入 data/limit_up_research/YYYYMMDD_limit_up_with_sector.json
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 项目根目录：plugins/data_collection/limit_up -> 上3级
PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = PROJECT_ROOT / "data" / "limit_up_research"


def _leader_score_and_reason(leader: Dict[str, Any], rank: int) -> tuple[int, str]:
    """
    龙头打分与理由。指标：涨停时间、连板数、流通市值 30–80 亿、换手率 10–20%、板块地位(排名)。
    返回 (score_0_100, reason_str)。
    """
    reasons = []
    score = 0
    cont = leader.get("continuous_limit_up_count") or 0
    if cont >= 3:
        score += 35
        reasons.append("3连板及以上")
    elif cont >= 2:
        score += 25
        reasons.append("2连板")
    else:
        score += 10
        reasons.append("首板")

    t = leader.get("limit_up_time") or ""
    if t and t <= "09:35:00":
        score += 25
        reasons.append("早盘封板")
    elif t and t <= "10:30:00":
        score += 15
        reasons.append("上午封板")
    else:
        score += 5
        reasons.append("午后封板")

    mv = leader.get("float_mv") or 0
    if 3e9 <= mv <= 8e9:
        score += 20
        reasons.append("流通市值30-80亿")
    elif 0 < mv < 3e9:
        score += 10
        reasons.append("小市值")
    else:
        score += 5
        reasons.append("大市值")

    turn = leader.get("turnover_rate")
    if turn is not None:
        if 10 <= turn <= 20:
            score += 15
            reasons.append("换手10-20%")
        elif 5 <= turn < 10:
            score += 10
            reasons.append("换手5-10%")
        else:
            score += 5

    if rank == 0:
        reasons.append("板块内率先/领涨")
        score += 10
    score = min(100, score)
    return score, "；".join(reasons)


def tool_write_limit_up_with_sector(
    date: Optional[str] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    拉取当日涨停、板块热度与龙头，写入 data/limit_up_research/YYYYMMDD_limit_up_with_sector.json。
    可选 output_path 覆盖默认路径。
    返回: success, date, path, sectors_count, limit_up_count
    """
    from plugins.data_collection.limit_up.fetch_limit_up import tool_fetch_limit_up_stocks
    from plugins.data_collection.limit_up.sector_heat import tool_sector_heat_score

    from datetime import datetime
    dt = date or datetime.now().strftime("%Y%m%d")

    out = tool_fetch_limit_up_stocks(date=dt)
    if not out.get("success"):
        return {
            "success": False,
            "error": out.get("error", "获取涨停股失败"),
            "date": dt,
            "path": None,
        }
    limit_up_data = out.get("data") or []

    heat = tool_sector_heat_score(date=dt, limit_up_data=limit_up_data, sector_data=None)
    if not heat.get("success"):
        return {
            "success": False,
            "error": heat.get("error", "板块热度计算失败"),
            "date": dt,
            "path": None,
        }
    sectors = heat.get("sectors") or []

    # 为每个板块的龙头加上 score 与 reason
    for sec in sectors:
        for i, L in enumerate(sec.get("leaders") or []):
            sc, reason = _leader_score_and_reason(L, i)
            L["leader_score"] = sc
            L["leader_reason"] = reason

    path = output_path
    if not path:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = str(OUTPUT_DIR / f"{dt}_limit_up_with_sector.json")
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "date": dt,
        "limit_up_list": limit_up_data,
        "sectors": sectors,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.exception("写入文件失败: %s", path)
        return {
            "success": False,
            "error": str(e),
            "date": dt,
            "path": path,
        }

    return {
        "success": True,
        "date": dt,
        "path": path,
        "sectors_count": len(sectors),
        "limit_up_count": len(limit_up_data),
    }


def _phase_to_strategy(phase: str) -> str:
    """板块周期 -> 建议策略"""
    if phase == "启动":
        return "次日低吸"
    if phase == "发酵":
        return "3-5日回调"
    if phase == "分歧":
        return "双底买入"
    if phase == "高潮":
        return "观望/龙头持股"
    return "退潮/观望"


def tool_limit_up_daily_flow(
    date: Optional[str] = None,
    write_json: bool = True,
    write_report: bool = True,
    send_feishu: bool = False,
) -> Dict[str, Any]:
    """
    每日盘后自动化流程：拉取涨停+板块热度+龙头 → 写 JSON → 生成次日观察列表 Markdown 报告。
    可由 OpenClaw cron 或脚本在 15:30 后触发。
    """
    from datetime import datetime
    dt = date or datetime.now().strftime("%Y%m%d")

    if write_json:
        out = tool_write_limit_up_with_sector(date=dt)
        if not out.get("success"):
            return {"success": False, "error": out.get("error"), "date": dt}
        json_path = out.get("path")
    else:
        json_path = str(OUTPUT_DIR / f"{dt}_limit_up_with_sector.json")
        if not Path(json_path).exists():
            return {"success": False, "error": "JSON 不存在且未执行写入", "date": dt}

    if not write_report:
        return {"success": True, "date": dt, "json_path": json_path, "report_path": None}

    with open(json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    sectors = payload.get("sectors") or []
    # 次日观察列表：按板块列出龙头并标记建议策略
    lines = [
        f"# 涨停回马枪 · 次日观察列表\n",
        f"**日期** {dt}\n",
        "",
        "## 热点板块与龙头",
        "",
        "| 板块 | 热度 | 周期 | 建议策略 | 龙头(代码/名称/连板/龙头分) |",
        "|------|------|------|----------|---------------------------|",
    ]
    for sec in sectors[:25]:
        name = sec.get("name", "")
        score = sec.get("score", 0)
        phase = sec.get("phase", "")
        strategy = _phase_to_strategy(phase)
        leaders = sec.get("leaders") or []
        leader_str = "；".join(
            f"{L.get('code')} {L.get('name', '')}({L.get('continuous_limit_up_count', 0)}板/龙头分{L.get('leader_score', 0)})"
            for L in leaders[:3]
        ) or "-"
        lines.append(f"| {name} | {score} | {phase} | {strategy} | {leader_str} |")
    lines.extend(["", "## 说明", "", "- **次日低吸**：启动期龙头，次日低开 2-5% 可考虑低吸。", "- **3-5日回调**：发酵期龙头，回调 5-10% 缩量止跌可关注。", "- **双底买入**：分歧期龙头，双底突破颈线可关注。", ""])
    report_path = OUTPUT_DIR / f"{dt}_report.md"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    if send_feishu:
        try:
            from merged.send_feishu_notification import tool_send_feishu_notification
            content = "\n".join(lines[:50])
            tool_send_feishu_notification(notification_type="message", message=content[:2000], title=f"涨停回马枪 {dt}")
        except Exception as e:
            logger.warning("飞书推送失败: %s", e)

    return {
        "success": True,
        "date": dt,
        "json_path": json_path,
        "report_path": str(report_path),
        "sectors_count": len(sectors),
    }
