"""
预测记录模块
统一记录用户即时预测和定时任务预测的结果
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import pytz

from src.logger_config import get_module_logger

logger = get_module_logger(__name__)

# 预测记录存储路径
PREDICTION_RECORDS_DIR = Path("data/prediction_records")
PREDICTION_DB_PATH = PREDICTION_RECORDS_DIR / "prediction_records.db"


def record_prediction(
    prediction_type: str,  # 'index'/'etf'/'option'
    symbol: str,  # 标的代码（指数代码/ETF代码/期权合约代码）
    prediction: dict,  # 包含upper, lower, timestamp, method, confidence等
    source: str = 'on_demand',  # 'on_demand'（用户即时预测）或 'scheduled'（定时任务预测）
    actual_range: dict = None,  # 收盘后填入实际价格范围
    config: dict = None
) -> bool:
    """
    记录预测结果，用于后续准确性评估
    
    Args:
        prediction_type: 预测类型 'index'/'etf'/'option'
        symbol: 标的代码
        prediction: 预测结果字典，必须包含：
            - upper: 预测上轨
            - lower: 预测下轨
            - current_price: 当前价格
            - timestamp: 预测时间戳
            - method: 预测方法（'GARCH'/'综合方法'等）
            - confidence: 置信度
            - range_pct: 波动范围百分比（可选）
        source: 预测来源 'on_demand'（用户即时预测）或 'scheduled'（定时任务预测）
        actual_range: 实际价格范围（收盘后填入），包含：
            - actual_high: 实际最高价
            - actual_low: 实际最低价
            - actual_close: 实际收盘价
            - hit: 是否命中区间（布尔值）
        config: 系统配置
    
    Returns:
        bool: 是否成功记录
    """
    try:
        # 确保目录存在
        PREDICTION_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
        
        # 获取当前日期
        tz_shanghai = pytz.timezone('Asia/Shanghai')
        now = datetime.now(tz_shanghai)
        date_str = now.strftime('%Y%m%d')
        
        # 构建记录
        record = {
            'date': date_str,
            'timestamp': now.isoformat(),
            'prediction_type': prediction_type,
            'symbol': symbol,
            'source': source,  # 'on_demand' 或 'scheduled'
            'prediction': {
                'upper': prediction.get('upper'),
                'lower': prediction.get('lower'),
                'current_price': prediction.get('current_price'),
                'method': prediction.get('method', '未知'),
                'confidence': prediction.get('confidence', 0.5),
                'range_pct': prediction.get('range_pct'),
            },
            'actual_range': actual_range,  # 收盘后填入
            'verified': actual_range is not None  # 是否已验证（收盘后）
        }
        
        # 如果已提供实际范围，计算是否命中
        if actual_range:
            upper = prediction.get('upper')
            lower = prediction.get('lower')
            actual_high = actual_range.get('actual_high')
            actual_low = actual_range.get('actual_low')
            
            if upper and lower and actual_high and actual_low:
                # 命中条件：实际最高价和最低价都在预测区间内
                hit = (actual_high <= upper) and (actual_low >= lower)
                record['actual_range']['hit'] = hit
        
        # 保存到JSON文件（按日期）
        json_file = PREDICTION_RECORDS_DIR / f"predictions_{date_str}.json"
        
        # 读取现有记录
        if json_file.exists():
            with open(json_file, 'r', encoding='utf-8') as f:
                records = json.load(f)
        else:
            records = []
        
        # 添加新记录
        records.append(record)
        
        # 保存
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        
        # 同时保存到SQLite数据库（可选，用于快速查询）
        _save_to_database(record)
        
        logger.debug(f"预测记录已保存: {prediction_type}/{symbol} ({source})")
        return True
        
    except Exception as e:
        logger.error(f"保存预测记录失败: {e}", exc_info=True)
        return False


def _save_to_database(record: dict):
    """保存到SQLite数据库"""
    try:
        conn = sqlite3.connect(PREDICTION_DB_PATH)
        cursor = conn.cursor()
        
        # 创建表（如果不存在）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                prediction_type TEXT NOT NULL,
                symbol TEXT NOT NULL,
                source TEXT NOT NULL,
                upper REAL,
                lower REAL,
                current_price REAL,
                method TEXT,
                confidence REAL,
                range_pct REAL,
                actual_high REAL,
                actual_low REAL,
                actual_close REAL,
                hit INTEGER,
                verified INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 插入记录
        cursor.execute('''
            INSERT INTO predictions (
                date, timestamp, prediction_type, symbol, source,
                upper, lower, current_price, method, confidence, range_pct,
                actual_high, actual_low, actual_close, hit, verified
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            record['date'],
            record['timestamp'],
            record['prediction_type'],
            record['symbol'],
            record['source'],
            record['prediction'].get('upper'),
            record['prediction'].get('lower'),
            record['prediction'].get('current_price'),
            record['prediction'].get('method'),
            record['prediction'].get('confidence'),
            record['prediction'].get('range_pct'),
            record['actual_range'].get('actual_high') if record.get('actual_range') else None,
            record['actual_range'].get('actual_low') if record.get('actual_range') else None,
            record['actual_range'].get('actual_close') if record.get('actual_range') else None,
            record['actual_range'].get('hit') if record.get('actual_range') else None,
            1 if record.get('verified') else 0
        ))
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.warning(f"保存到数据库失败: {e}，仅使用JSON文件")


def update_actual_range(
    date: str,
    symbol: str,
    source: str,
    actual_range: dict
) -> bool:
    """
    收盘后更新实际价格范围
    
    Args:
        date: 日期（格式：YYYYMMDD）
        symbol: 标的代码
        source: 预测来源
        actual_range: 实际价格范围
    
    Returns:
        bool: 是否成功更新
    """
    try:
        json_file = PREDICTION_RECORDS_DIR / f"predictions_{date}.json"
        
        if not json_file.exists():
            logger.warning(f"预测记录文件不存在: {json_file}")
            return False
        
        # 读取记录
        with open(json_file, 'r', encoding='utf-8') as f:
            records = json.load(f)
        
        # 查找匹配的记录
        updated = False
        for record in records:
            if (record.get('symbol') == symbol and 
                record.get('source') == source and
                not record.get('verified', False)):
                
                # 更新实际范围
                record['actual_range'] = actual_range
                record['verified'] = True
                
                # 计算是否命中
                upper = record['prediction'].get('upper')
                lower = record['prediction'].get('lower')
                actual_high = actual_range.get('actual_high')
                actual_low = actual_range.get('actual_low')
                
                if upper and lower and actual_high and actual_low:
                    hit = (actual_high <= upper) and (actual_low >= lower)
                    record['actual_range']['hit'] = hit
                
                updated = True
        
        if updated:
            # 保存
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
            
            # 更新数据库
            _update_database_actual_range(date, symbol, source, actual_range)
            
            logger.info(f"已更新实际范围: {symbol} ({source})")
            return True
        else:
            logger.warning(f"未找到匹配的记录: {symbol} ({source})")
            return False
            
    except Exception as e:
        logger.error(f"更新实际范围失败: {e}", exc_info=True)
        return False


def _update_database_actual_range(date: str, symbol: str, source: str, actual_range: dict):
    """更新数据库中的实际范围"""
    try:
        conn = sqlite3.connect(PREDICTION_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE predictions
            SET actual_high = ?,
                actual_low = ?,
                actual_close = ?,
                hit = ?,
                verified = 1
            WHERE date = ? AND symbol = ? AND source = ? AND verified = 0
        ''', (
            actual_range.get('actual_high'),
            actual_range.get('actual_low'),
            actual_range.get('actual_close'),
            1 if actual_range.get('hit') else 0,
            date,
            symbol,
            source
        ))
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.warning(f"更新数据库失败: {e}")


def get_method_performance(
    lookback_days: int = 30,
    prediction_type: str = None,
    method: str = None
) -> Dict[str, Any]:
    """
    获取各方法的 historical performance
    
    Args:
        lookback_days: 回看天数
        prediction_type: 预测类型（可选，None表示所有类型）
        method: 方法名称（可选，None表示所有方法）
    
    Returns:
        dict: 各方法的表现统计
    """
    try:
        tz_shanghai = pytz.timezone('Asia/Shanghai')
        end_date = datetime.now(tz_shanghai)
        start_date = end_date - timedelta(days=lookback_days)
        
        # 从数据库查询
        conn = sqlite3.connect(PREDICTION_DB_PATH)
        cursor = conn.cursor()
        
        # 构建查询条件
        conditions = ["verified = 1", "date >= ?", "date <= ?"]
        params = [start_date.strftime('%Y%m%d'), end_date.strftime('%Y%m%d')]
        
        if prediction_type:
            conditions.append("prediction_type = ?")
            params.append(prediction_type)
        
        if method:
            conditions.append("method = ?")
            params.append(method)
        
        query = f'''
            SELECT method, 
                   COUNT(*) as total,
                   SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) as hits,
                   AVG(range_pct) as avg_range_pct,
                   AVG(confidence) as avg_confidence
            FROM predictions
            WHERE {' AND '.join(conditions)}
            GROUP BY method
        '''
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        
        conn.close()
        
        # 构建返回结果
        performance = {}
        for row in results:
            method_name, total, hits, avg_range_pct, avg_confidence = row
            hit_rate = hits / total if total > 0 else 0.0
            
            performance[method_name] = {
                'hit_rate': hit_rate,
                'avg_width': avg_range_pct or 0.0,
                'avg_confidence': avg_confidence or 0.5,
                'total_predictions': total,
                'hits': hits
            }
        
        return performance
        
    except Exception as e:
        logger.error(f"获取方法表现失败: {e}", exc_info=True)
        return {}
