#!/usr/bin/env python3
"""
预测验证脚本

每日收盘后运行，读取当日实际行情数据，验证预测准确率。

使用方法：
    python scripts/verify_predictions.py --date 20260328 --symbol 510300
    
Cron 调度（crontab：分 时 日 月 周）：
    30 15 * * 1-5   # 每个交易日 15:30（建议略晚于盘后采集，如 35 分见 workflows/prediction_verification.yaml）
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.logger_config import get_module_logger
from src.prediction_normalizer import PRICE_RANGES, process_prediction
from src.data_collector import fetch_index_daily_em

logger = get_module_logger(__name__)

# 数据路径
PREDICTION_RECORDS_DIR = project_root / "data" / "prediction_records"
ETF_DAILY_DIR = project_root / "data" / "cache" / "etf_daily"
ETF_MINUTE_DIR = project_root / "data" / "cache" / "etf_minute"
INDEX_DAILY_DIR = project_root / "data" / "cache" / "index_daily"

_prediction_quality_cache: Optional[Dict[str, Any]] = None


def _get_prediction_quality_config() -> Dict[str, Any]:
    """与落库一致的质量门禁参数（来自合并后配置 prediction_quality；来源：config/domains/risk_quality.yaml）。"""
    global _prediction_quality_cache
    if _prediction_quality_cache is None:
        try:
            from src.config_loader import load_system_config

            raw = load_system_config(use_cache=True).get("prediction_quality")
            _prediction_quality_cache = raw if isinstance(raw, dict) else {}
        except Exception:
            _prediction_quality_cache = {}
    return _prediction_quality_cache


def _bounds_for_verify(record: Dict[str, Any]) -> tuple[float, float]:
    """
    取用于比对的上下轨：新记录在落库时已标准化；旧记录可能在 JSON 里仍为指数点量级，
    此处用与落库相同逻辑再算一遍，避免历史脏数据导致准确率恒为 0。
    """
    pred = record.get("prediction") or {}
    sym = record.get("symbol") or ""
    u = pred.get("upper")
    l = pred.get("lower")
    c = pred.get("current_price")
    try:
        fu, fl = float(u), float(l)
    except (TypeError, ValueError):
        return 0.0, 0.0
    if sym in PRICE_RANGES and c is not None:
        try:
            nu, nl, _, _, _ = process_prediction(
                float(u),
                float(l),
                float(c),
                sym,
                quality_gate=_get_prediction_quality_config(),
            )
            return nu, nl
        except Exception:
            return fu, fl
    return fu, fl


def get_actual_prices_from_parquet(symbol: str, date: str) -> Optional[Dict[str, float]]:
    """
    从 parquet 文件获取实际行情数据
    
    Args:
        symbol: 标的代码 (e.g., '510300')
        date: 日期 (格式: YYYYMMDD)
        
    Returns:
        dict: {'high': float, 'low': float, 'close': float} 或 None
    """
    import pandas as pd
    
    # 尝试从日线数据读取
    daily_path = ETF_DAILY_DIR / symbol / f"{date}.parquet"
    
    if daily_path.exists():
        try:
            df = pd.read_parquet(daily_path)
            if len(df) > 0:
                # 尝试不同的列名
                high_col = '最高' if '最高' in df.columns else 'high'
                low_col = '最低' if '最低' in df.columns else 'low'
                close_col = '收盘' if '收盘' in df.columns else 'close'
                
                return {
                    'high': float(df[high_col].max()),
                    'low': float(df[low_col].min()),
                    'close': float(df[close_col].iloc[-1])
                }
        except Exception as e:
            logger.error(f"读取日线数据失败 {daily_path}: {e}")
    
    # 尝试从分钟数据读取
    minute_path = ETF_MINUTE_DIR / symbol / f"{date}.parquet"
    
    if minute_path.exists():
        try:
            df = pd.read_parquet(minute_path)
            if len(df) > 0:
                high_col = '最高' if '最高' in df.columns else 'high'
                low_col = '最低' if '最低' in df.columns else 'low'
                close_col = '收盘' if '收盘' in df.columns else 'close'
                
                return {
                    'high': float(df[high_col].max()),
                    'low': float(df[low_col].min()),
                    'close': float(df[close_col].iloc[-1])
                }
        except Exception as e:
            logger.error(f"读取分钟数据失败 {minute_path}: {e}")
    
    logger.debug("未找到 %s 在 %s 的日线/分钟 parquet", symbol, date)
    return None

def verify_prediction_record(
    record: Dict[str, Any],
    actual_prices: Dict[str, float]
) -> Dict[str, Any]:
    """
    验证单条预测记录
    
    Args:
        record: 预测记录
        actual_prices: 实际价格 {'high': float, 'low': float, 'close': float}
        
    Returns:
        dict: 更新后的记录
    """
    upper, lower = _bounds_for_verify(record)
    
    actual_high = actual_prices['high']
    actual_low = actual_prices['low']
    actual_close = actual_prices['close']
    
    # 判断是否命中：实际最高价和最低价都在预测区间内
    hit = (actual_high <= upper) and (actual_low >= lower)
    
    # 计算覆盖率
    if upper > lower:
        # 预测区间覆盖了多少实际区间
        pred_range = upper - lower
        actual_range = actual_high - actual_low
        
        # 实际区间有多少在预测区间内
        overlap_low = max(lower, actual_low)
        overlap_high = min(upper, actual_high)
        overlap_range = max(0, overlap_high - overlap_low)
        
        coverage_rate = overlap_range / actual_range if actual_range > 0 else 0
    else:
        coverage_rate = 0
    
    # 更新记录
    record['actual_range'] = {
        'actual_high': actual_high,
        'actual_low': actual_low,
        'actual_close': actual_close,
        'hit': hit,
        'coverage_rate': coverage_rate
    }
    record['verified'] = True
    
    return record

def verify_predictions_for_date(date: str, symbol: Optional[str] = None) -> Dict[str, Any]:
    """
    验证指定日期的所有预测记录
    
    Args:
        date: 日期 (格式: YYYYMMDD)
        symbol: 标的代码（可选，None 表示验证所有标的）
        
    Returns:
        dict: 验证统计 {'verified': int, 'hit': int, 'miss': int, 'accuracy': float}
    """
    json_file = PREDICTION_RECORDS_DIR / f"predictions_{date}.json"
    
    if not json_file.exists():
        logger.warning(f"预测记录文件不存在: {json_file}")
        return {'verified': 0, 'hit': 0, 'miss': 0, 'accuracy': 0}
    
    # 读取预测记录
    with open(json_file, 'r', encoding='utf-8') as f:
        records = json.load(f)
    
    verified_count = 0
    hit_count = 0
    miss_count = 0
    skipped_no_price: Dict[str, int] = {}

    for record in records:
        # 跳过已验证的记录
        if record.get('verified', False):
            continue
        
        # 过滤标的（默认 None = 验证当日文件内全部标的）
        if symbol is not None and record.get("symbol") != symbol:
            continue
        
        # 获取实际行情
        record_symbol = record.get('symbol', '510300')
        actual_prices = get_actual_prices_from_parquet(record_symbol, date)
        
        if not actual_prices:
            skipped_no_price[record_symbol] = skipped_no_price.get(record_symbol, 0) + 1
            continue
        
        # 验证预测
        record = verify_prediction_record(record, actual_prices)
        
        # 统计
        verified_count += 1
        if record['actual_range']['hit']:
            hit_count += 1
        else:
            miss_count += 1

    if skipped_no_price:
        parts = [f"{s}×{n}" for s, n in sorted(skipped_no_price.items())]
        logger.warning(
            "无当日 parquet 行情，跳过 %s 条预测验证（date=%s，按标的 %s）。"
            "非交易日或盘后缓存未写入时属正常。",
            sum(skipped_no_price.values()),
            date,
            ", ".join(parts),
        )
    
    # 保存更新后的记录
    if verified_count > 0:
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
    
    # 计算准确率
    accuracy = hit_count / verified_count if verified_count > 0 else 0
    
    stats = {
        'verified': verified_count,
        'hit': hit_count,
        'miss': miss_count,
        'accuracy': accuracy
    }
    
    logger.info(f"验证完成: {verified_count} 条预测, {hit_count} 命中, 准确率 {accuracy:.2%}")
    
    return stats


def _iter_prediction_files() -> List[Path]:
    return sorted(PREDICTION_RECORDS_DIR.glob("predictions_*.json"))


def _load_index_daily_close(symbol: str, date: str) -> Optional[float]:
    import pandas as pd

    daily_path = INDEX_DAILY_DIR / symbol / f"{date}.parquet"
    if daily_path.exists():
        try:
            df = pd.read_parquet(daily_path)
            if len(df) > 0:
                close_col = '收盘' if '收盘' in df.columns else 'close'
                return float(df[close_col].iloc[-1])
        except Exception as e:
            logger.warning("读取指数日线缓存失败 %s: %s", daily_path, e)
    try:
        fetch_date = date.replace("-", "")
        df = fetch_index_daily_em(symbol=symbol[:6], start_date=fetch_date, end_date=fetch_date)
        if df is not None and not df.empty:
            close_col = '收盘' if '收盘' in df.columns else 'close'
            return float(pd.to_numeric(df[close_col], errors="coerce").dropna().iloc[-1])
    except Exception as e:
        logger.warning("拉取指数日线失败 %s/%s: %s", symbol, date, e)
    return None


def verify_direction_predictions_for_target_date(target_date: str) -> Dict[str, Any]:
    verified = 0
    hit = 0
    miss = 0

    for json_file in _iter_prediction_files():
        try:
            records = json.loads(json_file.read_text(encoding='utf-8'))
        except Exception:
            continue
        dirty = False
        for record in records:
            if record.get("prediction_type") != "index_direction":
                continue
            if str(record.get("target_date") or "") != target_date:
                continue
            if record.get("direction_verified"):
                continue
            symbol = str(record.get("symbol") or "")
            if not symbol:
                continue
            prediction = record.get("prediction") if isinstance(record.get("prediction"), dict) else {}
            predicted_direction = str(prediction.get("direction") or "")
            if predicted_direction not in {"up", "down", "neutral"}:
                continue
            prev_trade_date = str(record.get("metadata", {}).get("trade_date") or "").replace("-", "")
            prev_close = _load_index_daily_close(symbol, prev_trade_date) if prev_trade_date else None
            target_close = _load_index_daily_close(symbol, target_date)
            if prev_close in (None, 0) or target_close is None:
                continue
            actual_direction = "up" if target_close > prev_close else "down" if target_close < prev_close else "neutral"
            ok = predicted_direction == actual_direction
            record["direction_verification"] = {
                "base_close": prev_close,
                "target_close": target_close,
                "actual_direction": actual_direction,
                "hit": ok,
                "verified_at": datetime.now().isoformat(),
            }
            record["direction_verified"] = True
            dirty = True
            verified += 1
            if ok:
                hit += 1
            else:
                miss += 1
        if dirty:
            json_file.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')

    accuracy = hit / verified if verified else 0.0
    return {"verified": verified, "hit": hit, "miss": miss, "accuracy": accuracy}

def generate_verification_report(date: str, stats: Dict[str, Any]) -> str:
    """
    生成验证报告（Markdown 格式）
    
    Args:
        date: 日期
        stats: 验证统计
        
    Returns:
        str: Markdown 格式报告
    """
    report = f"""## 📊 预测验证报告 - {date}

### 验证统计

| 指标 | 数值 |
|------|------|
| 验证预测数 | {stats['verified']} |
| 命中数 | {stats['hit']} |
| 未命中数 | {stats['miss']} |
| **准确率** | **{stats['accuracy']:.2%}** |

### 分析结论

"""
    
    if stats['accuracy'] >= 0.7:
        report += "✅ 预测准确率良好，模型表现优秀。\n"
    elif stats['accuracy'] >= 0.5:
        report += "⚠️ 预测准确率中等，建议优化参数。\n"
    else:
        report += "❌ 预测准确率偏低，需要检查模型和数据质量。\n"
    
    return report

def main():
    parser = argparse.ArgumentParser(description='验证预测记录')
    parser.add_argument('--date', type=str, required=True, help='日期 (YYYYMMDD)')
    parser.add_argument(
        '--symbol',
        type=str,
        default=None,
        help='仅验证该标的；省略则验证当日文件内全部标的',
    )
    parser.add_argument('--report', action='store_true', help='生成报告')
    
    args = parser.parse_args()
    
    logger.info(f"开始验证 {args.date} 的预测记录...")
    
    # 同日区间 + 次日方向 两类验证
    range_stats = verify_predictions_for_date(args.date, args.symbol)
    direction_stats = verify_direction_predictions_for_target_date(args.date)
    stats = {
        "verified": int(range_stats.get("verified", 0)) + int(direction_stats.get("verified", 0)),
        "hit": int(range_stats.get("hit", 0)) + int(direction_stats.get("hit", 0)),
        "miss": int(range_stats.get("miss", 0)) + int(direction_stats.get("miss", 0)),
    }
    stats["accuracy"] = stats["hit"] / stats["verified"] if stats["verified"] else 0.0
    stats["range_stats"] = range_stats
    stats["direction_stats"] = direction_stats
    
    # 生成报告
    if args.report and stats['verified'] > 0:
        report = generate_verification_report(args.date, stats)
        print(report)
        
        # 保存报告
        report_dir = project_root / "data" / "verification_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_file = report_dir / f"verification_{args.date}.md"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        logger.info(f"报告已保存: {report_file}")
    
    return stats

if __name__ == "__main__":
    main()
