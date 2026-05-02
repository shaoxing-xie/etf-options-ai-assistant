from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from plugins.analysis.predictors import (
    predict_chinext,
    predict_csi300,
    predict_csi500,
    predict_csi1000,
    predict_kc50,
    predict_shanghai,
)
from plugins.analysis.predictors.common import classify_quality_reason


ROOT = Path(__file__).resolve().parents[2]


def _counterevidence(prediction: Dict[str, Any]) -> List[str]:
    direction = str(prediction.get("direction") or "")
    signals = prediction.get("signals") if isinstance(prediction.get("signals"), dict) else {}
    score = float((prediction.get("score_breakdown") or {}).get("total_score") or 0.0)
    reasons: List[str] = []
    if direction == "up":
        if score < 0.12:
            reasons.append("总分边际偏弱，若资金端转负可能翻转")
        if isinstance(signals.get("ret10"), (int, float)) and float(signals["ret10"]) > 0.05:
            reasons.append("短线涨幅偏高，存在技术性回撤压力")
    elif direction == "down":
        if score > -0.12:
            reasons.append("看空分数不强，若权重板块反弹可能转为震荡")
        if isinstance(signals.get("ret10"), (int, float)) and float(signals["ret10"]) < -0.05:
            reasons.append("短线超跌后存在反抽风险")
    else:
        reasons.append("方向中性，边际消息冲击即可打破平衡")
    if isinstance(signals.get("market_main_force_score"), (int, float)):
        m = float(signals["market_main_force_score"])
        if (direction == "up" and m < 0) or (direction == "down" and m > 0):
            reasons.append("资金流方向与预测存在背离")
    if not reasons:
        reasons.append("关键因子未形成一致性共振，方向稳健性一般")
    return reasons[:3]


def _meta(trade_date: str, predict_for_trade_date: str, run_id: str, quality_status: str) -> Dict[str, Any]:
    return {
        "schema_name": "six_index_next_day_direction_event_v1",
        "schema_version": "1.0.0",
        "task_id": "six-index-next-day-prediction",
        "run_id": run_id,
        "data_layer": "L3",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "trade_date": trade_date,
        "predict_for_trade_date": predict_for_trade_date,
        "quality_status": quality_status,
        "source_tools": ["rule_v1_predictors"],
        "lineage_refs": [],
    }


def predict_all(feature_doc: Dict[str, Any]) -> Dict[str, Any]:
    trade_date = str(feature_doc.get("trade_date") or feature_doc.get("_meta", {}).get("trade_date") or "").strip()
    predict_for_trade_date = str(
        feature_doc.get("predict_for_trade_date") or feature_doc.get("_meta", {}).get("predict_for_trade_date") or ""
    ).strip()
    run_id = str(feature_doc.get("_meta", {}).get("run_id") or datetime.now().strftime("%Y%m%dT%H%M%S"))
    feature_lineage = list(feature_doc.get("_meta", {}).get("lineage_refs") or [])
    indices = feature_doc.get("indices") if isinstance(feature_doc.get("indices"), dict) else {}

    predictions: List[Dict[str, Any]] = [
        predict_shanghai(indices.get("000001", {}), trade_date=trade_date, predict_for_trade_date=predict_for_trade_date),
        predict_csi300(indices.get("000300", {}), trade_date=trade_date, predict_for_trade_date=predict_for_trade_date),
        predict_kc50(indices.get("000688", {}), trade_date=trade_date, predict_for_trade_date=predict_for_trade_date),
        predict_chinext(indices.get("399006", {}), trade_date=trade_date, predict_for_trade_date=predict_for_trade_date),
        predict_csi500(indices.get("000905", {}), trade_date=trade_date, predict_for_trade_date=predict_for_trade_date),
        predict_csi1000(indices.get("000852", {}), trade_date=trade_date, predict_for_trade_date=predict_for_trade_date),
    ]
    for row in predictions:
        row["counterevidence"] = _counterevidence(row)
    prediction_statuses = [str(p.get("quality_status") or "info") for p in predictions]
    if not predictions:
        quality_status = "failed"
    elif any(status == "failed" for status in prediction_statuses):
        quality_status = "failed"
    elif any(status == "degraded" for status in prediction_statuses):
        quality_status = "degraded"
    else:
        quality_status = "info"
    meta = _meta(trade_date, predict_for_trade_date, run_id, quality_status)
    meta["lineage_refs"] = feature_lineage
    return {
        "_meta": meta,
        "trade_date": trade_date,
        "predict_for_trade_date": predict_for_trade_date,
        "predictions": predictions,
        "hotspot_snapshot": feature_doc.get("global_features", {}).get("hotspot_snapshot"),
    }


def persist_l3(doc: Dict[str, Any]) -> Path:
    td = str(doc.get("trade_date") or "").strip()
    path = ROOT / "data" / "decisions" / "six_index_next_day" / f"{td}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in doc.get("predictions") or []:
            line = {"_meta": doc.get("_meta", {}), "data": row}
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    doc.setdefault("_meta", {}).setdefault("lineage_refs", [])
    rel = str(path.relative_to(ROOT))
    if rel not in doc["_meta"]["lineage_refs"]:
        doc["_meta"]["lineage_refs"].append(rel)
    return path


def build_l4(doc: Dict[str, Any]) -> Dict[str, Any]:
    meta = dict(doc.get("_meta", {}))
    predictions = doc.get("predictions") or []
    l4_status = str(meta.get("quality_status") or "info")
    if not predictions:
        l4_status = "failed"
    elif any(classify_quality_reason(str(x.get("degraded_reason") or "")) == "failed" for x in predictions):
        l4_status = "failed"
    elif any(str(x.get("quality_status") or "") == "degraded" for x in predictions):
        l4_status = "degraded"
    else:
        l4_status = "info"
    meta.update({"schema_name": "six_index_next_day_view_v1", "data_layer": "L4", "quality_status": l4_status})
    return {
        "_meta": meta,
        "trade_date": doc.get("trade_date"),
        "predict_for_trade_date": doc.get("predict_for_trade_date"),
        "predictions": predictions,
        "hotspot_snapshot": doc.get("hotspot_snapshot"),
        "summary": {
            "up_count": sum(1 for x in predictions if x.get("direction") == "up"),
            "down_count": sum(1 for x in predictions if x.get("direction") == "down"),
            "neutral_count": sum(1 for x in predictions if x.get("direction") == "neutral"),
        },
    }


def persist_l4(doc: Dict[str, Any]) -> Path:
    td = str(doc.get("trade_date") or "").strip()
    path = ROOT / "data" / "semantic" / "six_index_next_day" / f"{td}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.setdefault("_meta", {}).setdefault("lineage_refs", [])
    rel = str(path.relative_to(ROOT))
    if rel not in doc["_meta"]["lineage_refs"]:
        doc["_meta"]["lineage_refs"].append(rel)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
