"""
数据库索引优化脚本
为信号记录表和预测记录表添加索引，提升查询性能
"""

import sqlite3
from pathlib import Path
from typing import Dict, List, Tuple, Any
from datetime import datetime

# 数据库路径
# 脚本在 scripts/ 目录下，需要回到项目根目录
BASE_DIR = Path(__file__).parent.parent  # etf-options-ai-assistant 目录
SIGNAL_DB_PATH = BASE_DIR / "data" / "signal_records" / "signal_records.db"

# 预测记录数据库路径（统一使用当前项目根目录下的数据库）
PREDICTION_DB_PATH = BASE_DIR / "data" / "prediction_records" / "prediction_records.db"


def get_existing_indexes(conn: sqlite3.Connection, table_name: str) -> List[str]:
    """获取表中已存在的索引"""
    cursor = conn.cursor()
    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='{table_name}'")
    indexes = [row[0] for row in cursor.fetchall()]
    return indexes


def create_index_if_not_exists(
    conn: sqlite3.Connection,
    table_name: str,
    index_name: str,
    columns: List[str],
    unique: bool = False
) -> bool:
    """
    创建索引（如果不存在）
    
    Args:
        conn: 数据库连接
        table_name: 表名
        index_name: 索引名称
        columns: 列名列表
        unique: 是否唯一索引
    
    Returns:
        bool: 是否成功创建
    """
    try:
        cursor = conn.cursor()
        
        # 检查索引是否已存在
        existing_indexes = get_existing_indexes(conn, table_name)
        if index_name in existing_indexes:
            print(f"  索引 {index_name} 已存在，跳过")
            return True
        
        # 构建索引SQL
        unique_keyword = "UNIQUE" if unique else ""
        columns_str = ", ".join(columns)
        sql = f"CREATE {unique_keyword} INDEX IF NOT EXISTS {index_name} ON {table_name} ({columns_str})"
        
        cursor.execute(sql)
        conn.commit()
        print(f"  ✅ 创建索引: {index_name} ON {table_name}({columns_str})")
        return True
        
    except Exception as e:
        print(f"  ❌ 创建索引 {index_name} 失败: {str(e)}")
        return False


def optimize_signal_records_indexes(db_path: Path) -> Dict[str, bool]:
    """
    优化信号记录表的索引
    
    索引策略：
    1. signal_id: 唯一索引（已存在，但确保存在）
    2. strategy: 单列索引（按策略查询）
    3. status: 单列索引（按状态查询）
    4. date: 单列索引（按日期查询）
    5. etf_symbol: 单列索引（按ETF代码查询）
    6. (strategy, date): 复合索引（按策略和日期查询）
    7. (status, date): 复合索引（按状态和日期查询）
    8. (etf_symbol, date): 复合索引（按ETF和日期查询）
    9. created_at: 单列索引（按创建时间排序）
    """
    results = {}
    
    if not db_path.exists():
        print(f"⚠️  数据库文件不存在: {db_path}")
        print("   将在首次写入时自动创建")
        return results
    
    print(f"\n优化信号记录表索引: {db_path}")
    
    try:
        conn = sqlite3.connect(str(db_path))
        
        # 1. signal_id 唯一索引（主键，通常已存在）
        results['idx_signal_id'] = create_index_if_not_exists(
            conn, 'signal_records', 'idx_signal_id', ['signal_id'], unique=True
        )
        
        # 2. strategy 单列索引
        results['idx_strategy'] = create_index_if_not_exists(
            conn, 'signal_records', 'idx_strategy', ['strategy']
        )
        
        # 3. status 单列索引
        results['idx_status'] = create_index_if_not_exists(
            conn, 'signal_records', 'idx_status', ['status']
        )
        
        # 4. date 单列索引
        results['idx_date'] = create_index_if_not_exists(
            conn, 'signal_records', 'idx_date', ['date']
        )
        
        # 5. etf_symbol 单列索引
        results['idx_etf_symbol'] = create_index_if_not_exists(
            conn, 'signal_records', 'idx_etf_symbol', ['etf_symbol']
        )
        
        # 6. (strategy, date) 复合索引
        results['idx_strategy_date'] = create_index_if_not_exists(
            conn, 'signal_records', 'idx_strategy_date', ['strategy', 'date']
        )
        
        # 7. (status, date) 复合索引
        results['idx_status_date'] = create_index_if_not_exists(
            conn, 'signal_records', 'idx_status_date', ['status', 'date']
        )
        
        # 8. (etf_symbol, date) 复合索引
        results['idx_etf_symbol_date'] = create_index_if_not_exists(
            conn, 'signal_records', 'idx_etf_symbol_date', ['etf_symbol', 'date']
        )
        
        # 9. created_at 单列索引（用于排序）
        results['idx_created_at'] = create_index_if_not_exists(
            conn, 'signal_records', 'idx_created_at', ['created_at']
        )
        
        conn.close()
        print("✅ 信号记录表索引优化完成")
        
    except Exception as e:
        print(f"❌ 优化信号记录表索引失败: {str(e)}")
        results['error'] = str(e)
    
    return results


def optimize_predictions_indexes(db_path: Path) -> Dict[str, bool]:
    """
    优化预测记录表的索引
    
    索引策略：
    1. date: 单列索引（按日期查询）
    2. prediction_type: 单列索引（按预测类型查询）
    3. symbol: 单列索引（按标的代码查询）
    4. source: 单列索引（按来源查询）
    5. method: 单列索引（按方法查询）
    6. verified: 单列索引（按验证状态查询）
    7. (date, prediction_type): 复合索引（按日期和类型查询）
    8. (prediction_type, method): 复合索引（按类型和方法查询）
    9. (date, symbol, source): 复合索引（按日期、标的、来源查询）
    10. (verified, date): 复合索引（按验证状态和日期查询）
    11. created_at: 单列索引（按创建时间排序）
    """
    results = {}
    
    if not db_path.exists():
        print(f"⚠️  数据库文件不存在: {db_path}")
        print("   将在首次写入时自动创建")
        return results
    
    print(f"\n优化预测记录表索引: {db_path}")
    
    try:
        conn = sqlite3.connect(str(db_path))
        
        # 1. date 单列索引
        results['idx_date'] = create_index_if_not_exists(
            conn, 'predictions', 'idx_date', ['date']
        )
        
        # 2. prediction_type 单列索引
        results['idx_prediction_type'] = create_index_if_not_exists(
            conn, 'predictions', 'idx_prediction_type', ['prediction_type']
        )
        
        # 3. symbol 单列索引
        results['idx_symbol'] = create_index_if_not_exists(
            conn, 'predictions', 'idx_symbol', ['symbol']
        )
        
        # 4. source 单列索引
        results['idx_source'] = create_index_if_not_exists(
            conn, 'predictions', 'idx_source', ['source']
        )
        
        # 5. method 单列索引
        results['idx_method'] = create_index_if_not_exists(
            conn, 'predictions', 'idx_method', ['method']
        )
        
        # 6. verified 单列索引
        results['idx_verified'] = create_index_if_not_exists(
            conn, 'predictions', 'idx_verified', ['verified']
        )
        
        # 7. (date, prediction_type) 复合索引
        results['idx_date_prediction_type'] = create_index_if_not_exists(
            conn, 'predictions', 'idx_date_prediction_type', ['date', 'prediction_type']
        )
        
        # 8. (prediction_type, method) 复合索引
        results['idx_prediction_type_method'] = create_index_if_not_exists(
            conn, 'predictions', 'idx_prediction_type_method', ['prediction_type', 'method']
        )
        
        # 9. (date, symbol, source) 复合索引
        results['idx_date_symbol_source'] = create_index_if_not_exists(
            conn, 'predictions', 'idx_date_symbol_source', ['date', 'symbol', 'source']
        )
        
        # 10. (verified, date) 复合索引
        results['idx_verified_date'] = create_index_if_not_exists(
            conn, 'predictions', 'idx_verified_date', ['verified', 'date']
        )
        
        # 11. created_at 单列索引（用于排序）
        results['idx_created_at'] = create_index_if_not_exists(
            conn, 'predictions', 'idx_created_at', ['created_at']
        )
        
        conn.close()
        print("✅ 预测记录表索引优化完成")
        
    except Exception as e:
        print(f"❌ 优化预测记录表索引失败: {str(e)}")
        results['error'] = str(e)
    
    return results


def analyze_query_performance(conn: sqlite3.Connection, table_name: str, query: str, params: Tuple = ()) -> Dict[str, Any]:
    """
    分析查询性能（使用EXPLAIN QUERY PLAN）
    
    Args:
        conn: 数据库连接
        table_name: 表名
        query: 查询SQL
        params: 查询参数
    
    Returns:
        Dict: 查询计划信息
    """
    try:
        cursor = conn.cursor()
        explain_query = f"EXPLAIN QUERY PLAN {query}"
        cursor.execute(explain_query, params)
        plan = cursor.fetchall()
        
        return {
            'query': query,
            'plan': plan,
            'uses_index': any('USING INDEX' in str(row) for row in plan)
        }
    except Exception as e:
        return {
            'query': query,
            'error': str(e)
        }


def main():
    """主函数"""
    print("=" * 60)
    print("数据库索引优化脚本")
    print("=" * 60)
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 确保目录存在
    SIGNAL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREDICTION_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # 优化信号记录表索引
    signal_results = optimize_signal_records_indexes(SIGNAL_DB_PATH)
    
    # 优化预测记录表索引
    prediction_results = optimize_predictions_indexes(PREDICTION_DB_PATH)
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("优化结果汇总")
    print("=" * 60)
    
    signal_success = sum(1 for v in signal_results.values() if v is True)
    signal_total = len([k for k in signal_results.keys() if k != 'error'])
    print(f"信号记录表: {signal_success}/{signal_total} 个索引创建成功")
    
    prediction_success = sum(1 for v in prediction_results.values() if v is True)
    prediction_total = len([k for k in prediction_results.keys() if k != 'error'])
    print(f"预测记录表: {prediction_success}/{prediction_total} 个索引创建成功")
    
    print("\n✅ 索引优化完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
