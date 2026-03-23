"""
飞书数据处理器
处理从飞书下载的数据，更新本地缓存
"""

import json
import pandas as pd
from typing import Dict
from datetime import datetime
from src.logger_config import get_module_logger
from src.data_cache import save_option_greeks_cache

logger = get_module_logger(__name__)


def process_index_minute_data(content: Dict, filename: str) -> bool:
    """
    处理指数分钟数据，更新本地缓存
    
    Args:
        content: 数据内容（字典）
        filename: 文件名（如 "index_000300_20260130.json"）
    
    Returns:
        bool: 处理是否成功
    """
    try:
        symbol = content.get("symbol", "000300")
        period = content.get("period", "30")
        data_list = content.get("data", [])
        
        if not data_list:
            logger.warning(f"指数分钟数据为空: {filename}")
            return False
        
        # 转换为DataFrame
        df = pd.DataFrame(data_list)
        
        # 确保必要的列存在
        required_columns = ["时间", "开盘", "收盘", "最高", "最低", "成交量"]
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logger.warning(f"指数分钟数据缺少列: {filename}, 缺失: {missing_columns}")
            return False
        
        # 保存到缓存（根据周期保存）
        # save_index_minute_cache函数签名: (symbol, period, df, config)
        try:
            from src.data_cache import save_index_minute_cache
            save_index_minute_cache(symbol, period, df)
        except Exception as e:
            logger.warning(f"保存指数分钟缓存失败: {symbol}, {period}, {e}")
        
        logger.info(f"指数分钟数据处理成功: {filename}, 符号={symbol}, 周期={period}, 记录数={len(df)}")
        return True
        
    except Exception as e:
        logger.error(f"处理指数分钟数据失败: {filename}, {e}", exc_info=True)
        return False


def process_etf_minute_data(content: Dict, filename: str) -> bool:
    """
    处理ETF分钟数据，更新本地缓存
    
    Args:
        content: 数据内容（字典）
        filename: 文件名（如 "etf_510300_20260130.json"）
    
    Returns:
        bool: 处理是否成功
    """
    try:
        symbol = content.get("symbol", "510300")
        period = content.get("period", "30")
        data_list = content.get("data", [])
        
        if not data_list:
            logger.warning(f"ETF分钟数据为空: {filename}")
            return False
        
        # 转换为DataFrame
        df = pd.DataFrame(data_list)
        
        # 确保必要的列存在
        required_columns = ["时间", "开盘", "收盘", "最高", "最低", "成交量"]
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logger.warning(f"ETF分钟数据缺少列: {filename}, 缺失: {missing_columns}")
            return False
        
        # 保存到缓存（根据周期保存）
        # save_etf_minute_cache函数签名: (symbol, period, df, config)
        try:
            from src.data_cache import save_etf_minute_cache
            save_etf_minute_cache(symbol, period, df)
        except Exception as e:
            logger.warning(f"保存ETF分钟缓存失败: {symbol}, {period}, {e}")
        
        logger.info(f"ETF分钟数据处理成功: {filename}, 符号={symbol}, 周期={period}, 记录数={len(df)}")
        return True
        
    except Exception as e:
        logger.error(f"处理ETF分钟数据失败: {filename}, {e}", exc_info=True)
        return False


def process_option_greeks_data(content: Dict, filename: str) -> bool:
    """
    处理期权Greeks数据，更新本地缓存
    
    当前Coze插件 `greeks_data.py` 生成的文件结构（支持多合约）：
    {
        "timestamp": "YYYYMMDDHHMMSS",
        "contract_code": "10010891,10010892",
        "records": [
            {
                "contract_code": "10010891",
                "time": "YYYYMMDDHHMMSS",
                "Delta": "0.1466",
                "Gamma": "1.4541",
                ...
            },
            {
                "contract_code": "10010892",
                "time": "YYYYMMDDHHMMSS",
                "Delta": "0.1234",
                ...
            }
        ],
        "total_count": N
    }
    
    注意：records 列表中的每个元素已经是一个宽表记录（包含 contract_code 和所有 Greeks 字段）。
    
    你期望的缓存粒度：**每个合约每个采集时刻只保存一条记录（宽表）**，按时间序列追加并去重。
    
    本函数将：
    - 遍历 records 列表，处理每个合约的数据
    - 以每个 record 的 contract_code 作为合约代码
    - 以 timestamp 的前8位（YYYYMMDD）作为日期
    - 将每个宽表记录写入对应合约的缓存（追加模式，按时间戳去重）
    """
    try:
        # 添加：输出文件内容结构，便于调试
        logger.info(f"Greek数据文件结构: {filename}, keys={list(content.keys())}")
        
        # 获取外层 timestamp（用于日期提取）
        outer_timestamp = content.get("timestamp", "")
        logger.info(f"外层timestamp: {outer_timestamp}")
        
        # 获取 records 列表（支持多合约）
        records = content.get("records") or []
        if not isinstance(records, list) or len(records) == 0:
            logger.warning(f"期权Greeks数据 records 为空: {filename}, records类型={type(records)}")
            return False
        
        logger.info(f"Greek数据包含 {len(records)} 条记录")
        # 输出第一条记录示例
        if records:
            first_record = records[0]
            logger.info(f"第一条记录示例: keys={list(first_record.keys()) if isinstance(first_record, dict) else 'Not a dict'}, contract_code={first_record.get('contract_code') if isinstance(first_record, dict) else 'N/A'}")
        
        success_count = 0
        error_count = 0
        
        # ========== 遍历每个合约的记录 ==========
        for i, record in enumerate(records):
            try:
                # 从 record 中获取合约代码
                contract_code = record.get("contract_code")
                if not contract_code:
                    logger.warning(f"期权Greeks记录缺少合约代码: {filename}, 记录索引={i}, record keys={list(record.keys()) if isinstance(record, dict) else 'Not a dict'}")
                    error_count += 1
                    continue
                
                # 添加：清理contract_code中的引号（防御性处理）
                contract_code_original = contract_code
                contract_code = str(contract_code).strip().strip('"').strip("'")
                if contract_code != str(contract_code_original):
                    logger.warning(f"清理contract_code: 原始='{contract_code_original}' -> 清理后='{contract_code}'")
                
                logger.debug(f"处理记录 {i+1}/{len(records)}: contract_code={contract_code}")
                
                # 提取时间戳：使用 record 中的 time 字段
                record_time = record.get("time") or outer_timestamp
                if not record_time:
                    logger.warning(f"期权Greeks记录缺少时间字段: {filename}, 合约={contract_code}, 记录索引={i}")
                    error_count += 1
                    continue
                
                # 提取日期（YYYYMMDD）
                date_str = record_time[:8] if isinstance(record_time, str) and len(record_time) >= 8 else datetime.now().strftime("%Y%m%d")
                
                # ========== 将宽表记录转换为 DataFrame ==========
                # record 已经是宽表格式（包含 contract_code, time, Delta, Gamma 等字段）
                # 直接转换为 DataFrame（一行）
                df = pd.DataFrame([record])
                
                # 确保 time 和采集时间列存在（用于去重）
                if "time" not in df.columns:
                    df["time"] = record_time
                if "采集时间" not in df.columns:
                    df["采集时间"] = record_time
                
                # 尝试将数值字段转换为数值类型（不影响无法转换的列）
                numeric_fields = ["Delta", "Gamma", "Theta", "Vega", "隐含波动率", "最新价", "理论价值", "行权价"]
                for col in df.columns:
                    if col in ("contract_code", "time", "采集时间"):
                        continue
                    if col in numeric_fields or any(keyword in str(col) for keyword in ["价", "率", "Delta", "Gamma", "Theta", "Vega"]):
                        try:
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                        except Exception as e:
                            logger.debug(f"数值列转换失败: col={col}, 错误: {e}", exc_info=True)
                
                # 保存到缓存（追加模式，按时间戳去重）
                try:
                    logger.debug(f"准备保存: contract_code='{contract_code}' (类型={type(contract_code)}), date={date_str}, DataFrame shape={df.shape}")
                    if save_option_greeks_cache(contract_code, df, date=date_str):
                        success_count += 1
                        logger.info(f"期权Greeks数据保存成功: 合约={contract_code}, 日期={date_str}, 数据行数={len(df)}")
                    else:
                        error_count += 1
                        logger.warning(f"期权Greeks数据保存失败: 合约={contract_code}, 日期={date_str}")
                except Exception as e:
                    error_count += 1
                    logger.error(f"保存期权Greeks缓存异常: 合约='{contract_code}', 日期={date_str}, 错误类型={type(e).__name__}, 错误={e}", exc_info=True)
                    
            except Exception as e:
                error_count += 1
                logger.error(f"处理期权Greeks记录异常: {filename}, 记录索引={i}, contract_code={record.get('contract_code') if isinstance(record, dict) else 'N/A'}, 错误类型={type(e).__name__}, 错误={e}", exc_info=True)
        
        # 返回处理结果
        if success_count > 0:
            logger.info(f"期权Greeks数据处理完成: {filename}, 成功={success_count}, 失败={error_count}, 总记录数={len(records)}")
            return True
        else:
            logger.error(f"期权Greeks数据处理失败: {filename}, 所有记录处理失败, 总记录数={len(records)}, 错误数={error_count}")
            return False
        
    except Exception as e:
        logger.error(f"处理期权Greeks数据失败: {filename}, 错误类型={type(e).__name__}, 错误={e}", exc_info=True)
        return False


def process_feishu_file(file_content: bytes, filename: str, subfolder: str) -> bool:
    """
    处理从飞书下载的文件
    
    Args:
        file_content: 文件内容（字节）
        filename: 文件名
        subfolder: 子文件夹名称（index_minute, etf_minute, option_greeks）
    
    Returns:
        bool: 处理是否成功
    """
    try:
        # 解析JSON内容
        content = json.loads(file_content.decode('utf-8'))
        
        # 根据子文件夹类型调用不同的处理函数
        if subfolder == "index_minute":
            return process_index_minute_data(content, filename)
        elif subfolder == "etf_minute":
            return process_etf_minute_data(content, filename)
        elif subfolder == "option_greeks":
            return process_option_greeks_data(content, filename)
        else:
            logger.warning(f"未知的子文件夹类型: {subfolder}, 文件名: {filename}")
            return False
            
    except json.JSONDecodeError as e:
        logger.error(f"JSON解析失败: {filename}, {e}")
        return False
    except Exception as e:
        logger.error(f"处理飞书文件失败: {filename}, {e}", exc_info=True)
        return False
