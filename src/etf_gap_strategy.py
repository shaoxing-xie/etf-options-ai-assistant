"""
ETF缺口策略模块
检测隔夜跳空并监控回补情况
"""

import pandas as pd
from typing import Dict, Any, Optional, List
from datetime import datetime
import pytz

from src.logger_config import get_module_logger
from src.data_collector import fetch_etf_daily_em, get_etf_current_price
from src.config_loader import load_system_config

logger = get_module_logger(__name__)


def detect_gap_at_opening(
    etf_symbol: str,
    opening_price: float,
    previous_close: float,
    gap_threshold: float = 0.008
) -> Optional[Dict[str, Any]]:
    """
    检测开盘跳空
    
    Args:
        etf_symbol: ETF代码（如 "510300"）
        opening_price: 当日开盘价
        previous_close: 前一日收盘价
        gap_threshold: 跳空阈值（默认0.8%，即0.008）
    
    Returns:
        dict: 如果检测到跳空，返回 {
            "gap_type": "向上跳空" | "向下跳空",
            "gap_pct": float,  # 跳空幅度（百分比）
            "opening_price": float,
            "previous_close": float,
            "needs_monitoring": True  # 需要监测回补
        }
        如果未检测到跳空，返回None
    """
    try:
        if opening_price is None or previous_close is None:
            return None
        
        if previous_close == 0:
            logger.warning(f"ETF {etf_symbol} 前一日收盘价为0，无法计算跳空")
            return None
        
        gap_pct = (opening_price - previous_close) / previous_close
        
        # 检查是否超过阈值
        if abs(gap_pct) >= gap_threshold:
            gap_type = "向上跳空" if gap_pct > 0 else "向下跳空"
            
            logger.info(f"检测到ETF {etf_symbol} {gap_type}: "
                       f"前收={previous_close:.4f}, 开盘={opening_price:.4f}, "
                       f"跳空幅度={gap_pct*100:.2f}%")
            
            return {
                "gap_type": gap_type,
                "gap_pct": gap_pct,
                "opening_price": opening_price,
                "previous_close": previous_close,
                "needs_monitoring": True,
                "detected_at": datetime.now(pytz.timezone('Asia/Shanghai')).strftime("%Y-%m-%d %H:%M:%S")
            }
        else:
            return None
            
    except Exception as e:
        logger.error(f"检测ETF {etf_symbol} 跳空失败: {e}", exc_info=True)
        return None


def check_gap_fillback(
    etf_symbol: str,
    gap_info: Dict[str, Any],
    current_price: Optional[float] = None,
    minute_data: Optional[pd.DataFrame] = None,
    fillback_threshold: float = 0.003  # 回补阈值：价格回到跳空区间内3%即认为回补
) -> Dict[str, Any]:
    """
    检查跳空是否回补（开盘后30分钟检查）
    
    Args:
        etf_symbol: ETF代码
        gap_info: 跳空信息（来自detect_gap_at_opening）
        current_price: 当前价格（如果为None则自动获取）
        minute_data: 分钟数据（如果为None则自动获取）
        fillback_threshold: 回补阈值（默认0.3%）
    
    Returns:
        dict: {
            "is_filled": bool,  # 是否已回补
            "fillback_pct": float,  # 回补幅度（相对于跳空幅度）
            "current_price": float,
            "signal_type": "买入" | "卖出" | None,
            "signal_strength": float,  # 0-1
            "reason": str
        }
    """
    try:
        gap_type = gap_info.get("gap_type")
        gap_pct = gap_info.get("gap_pct", 0)
        opening_price = gap_info.get("opening_price")
        previous_close = gap_info.get("previous_close")
        
        if gap_type is None or opening_price is None or previous_close is None:
            return {
                "is_filled": False,
                "fillback_pct": 0.0,
                "current_price": current_price or 0.0,
                "signal_type": None,
                "signal_strength": 0.0,
                "reason": "跳空信息不完整"
            }
        
        # 获取当前价格
        if current_price is None:
            current_price = get_etf_current_price(etf_symbol)
            if current_price is None:
                logger.warning(f"无法获取ETF {etf_symbol} 当前价格")
                return {
                    "is_filled": False,
                    "fillback_pct": 0.0,
                    "current_price": 0.0,
                    "signal_type": None,
                    "signal_strength": 0.0,
                    "reason": "无法获取当前价格"
                }
        
        # 计算回补情况
        # 向上跳空：如果价格回落至开盘价附近（或更低），认为回补
        # 向下跳空：如果价格回升至开盘价附近（或更高），认为回补
        
        if gap_type == "向上跳空":
            # 向上跳空回补：价格回落
            price_change_from_open = (current_price - opening_price) / opening_price
            # 如果价格回落超过阈值，认为回补
            is_filled = price_change_from_open <= -fillback_threshold
            
            if is_filled:
                fillback_pct = abs(price_change_from_open) / abs(gap_pct) if gap_pct != 0 else 0.0
                # 向上跳空回补后，通常是买入机会（价格回落至合理区间）
                signal_type = "买入"
                signal_strength = min(0.8, 0.5 + fillback_pct * 0.3)  # 回补越多，信号越强
                reason = f"向上跳空{gap_pct*100:.2f}%已回补{abs(price_change_from_open)*100:.2f}%，价格回落至合理区间，可考虑买入"
            else:
                fillback_pct = 0.0
                signal_type = None
                signal_strength = 0.0
                reason = f"向上跳空{gap_pct*100:.2f}%尚未回补，当前价格较开盘{price_change_from_open*100:+.2f}%"
                
        else:  # 向下跳空
            # 向下跳空回补：价格回升
            price_change_from_open = (current_price - opening_price) / opening_price
            # 如果价格回升超过阈值，认为回补
            is_filled = price_change_from_open >= fillback_threshold
            
            if is_filled:
                fillback_pct = abs(price_change_from_open) / abs(gap_pct) if gap_pct != 0 else 0.0
                # 向下跳空回补后，通常是卖出机会（价格回升至合理区间，可能是反弹）
                signal_type = "卖出"
                signal_strength = min(0.8, 0.5 + fillback_pct * 0.3)
                reason = f"向下跳空{abs(gap_pct)*100:.2f}%已回补{price_change_from_open*100:.2f}%，价格回升至合理区间，可考虑卖出"
            else:
                fillback_pct = 0.0
                signal_type = None
                signal_strength = 0.0
                reason = f"向下跳空{abs(gap_pct)*100:.2f}%尚未回补，当前价格较开盘{price_change_from_open*100:+.2f}%"
        
        logger.info(f"ETF {etf_symbol} 跳空回补检查: {gap_type}, "
                   f"当前价={current_price:.4f}, 开盘价={opening_price:.4f}, "
                   f"回补={is_filled}, 信号={signal_type}, 强度={signal_strength:.2f}")
        
        return {
            "is_filled": is_filled,
            "fillback_pct": fillback_pct,
            "current_price": current_price,
            "signal_type": signal_type,
            "signal_strength": signal_strength,
            "reason": reason,
            "price_change_from_open": price_change_from_open
        }
        
    except Exception as e:
        logger.error(f"检查ETF {etf_symbol} 跳空回补失败: {e}", exc_info=True)
        return {
            "is_filled": False,
            "fillback_pct": 0.0,
            "current_price": current_price or 0.0,
            "signal_type": None,
            "signal_strength": 0.0,
            "reason": f"检查失败: {str(e)}"
        }


def detect_etf_gaps_at_opening(
    etf_symbols: Optional[List[str]] = None,
    config: Optional[Dict] = None
) -> Dict[str, Dict[str, Any]]:
    """
    在开盘时检测所有ETF的跳空情况
    
    Args:
        etf_symbols: ETF代码列表，如果为None则从config读取
        config: 系统配置
    
    Returns:
        dict: {
            "510300": {
                "gap_info": {...},  # 跳空信息，如果检测到
                "has_gap": bool
            },
            ...
        }
    """
    try:
        if config is None:
            config = load_system_config()
        
        etf_config = config.get('etf_trading', {})
        gap_config = etf_config.get('gap_strategy', {})
        
        if not gap_config.get('enabled', True):
            logger.debug("缺口策略未启用，跳过检测")
            return {}
        
        gap_threshold = gap_config.get('gap_threshold', 0.008)  # 默认0.8%
        
        if etf_symbols is None:
            etf_symbols = etf_config.get('enabled_etfs', ['510300', '510050', '510500'])
        
        results: Dict[str, Dict[str, Any]] = {}
        
        for etf_symbol in etf_symbols:
            try:
                # 获取ETF日线数据（最近2天）
                etf_daily = fetch_etf_daily_em(
                    symbol=etf_symbol,
                    start_date=None,
                    end_date=None,
                    prefer_tushare=True
                )
                
                if etf_daily is None or etf_daily.empty or len(etf_daily) < 2:
                    logger.warning(f"ETF {etf_symbol} 日线数据不足，无法检测跳空")
                    results[etf_symbol] = {
                        "has_gap": False,
                        "gap_info": None,
                        "error": "数据不足"
                    }
                    continue
                
                # 获取前一日收盘价和当日开盘价
                # 注意：日线数据的最后一行是最近一个交易日
                previous_close = None
                opening_price = None
                
                # 找到日期列
                date_col = None
                for col in ['日期', 'date', '日期时间', 'datetime']:
                    if col in etf_daily.columns:
                        date_col = col
                        break
                
                if date_col:
                    etf_daily = etf_daily.sort_values(date_col).reset_index(drop=True)
                
                # 获取最后两行数据
                if len(etf_daily) >= 2:
                    # 倒数第二行：前一日
                    prev_row = etf_daily.iloc[-2]
                    # 最后一行：当日（如果当日数据已更新）
                    curr_row = etf_daily.iloc[-1]
                    
                    # 获取收盘价列
                    close_col = None
                    for col in ['收盘', 'close', '收盘价']:
                        if col in prev_row.index:
                            close_col = col
                            break
                    
                    # 获取开盘价列
                    open_col = None
                    for col in ['开盘', 'open', '开盘价']:
                        if col in curr_row.index:
                            open_col = col
                            break
                    
                    if close_col and open_col:
                        previous_close = float(prev_row[close_col])
                        opening_price = float(curr_row[open_col])
                    else:
                        logger.warning(f"ETF {etf_symbol} 日线数据缺少收盘/开盘列")
                        results[etf_symbol] = {
                            "has_gap": False,
                            "gap_info": None,
                            "error": "数据格式问题"
                        }
                        continue
                else:
                    logger.warning(f"ETF {etf_symbol} 日线数据不足2条")
                    results[etf_symbol] = {
                        "has_gap": False,
                        "gap_info": None,
                        "error": "数据不足"
                    }
                    continue
                
                # 检测跳空
                gap_info = detect_gap_at_opening(
                    etf_symbol=etf_symbol,
                    opening_price=opening_price,
                    previous_close=previous_close,
                    gap_threshold=gap_threshold
                )
                
                results[etf_symbol] = {
                    "has_gap": gap_info is not None,
                    "gap_info": gap_info,
                    "opening_price": opening_price,
                    "previous_close": previous_close
                }
                
            except Exception as e:
                logger.error(f"检测ETF {etf_symbol} 跳空失败: {e}", exc_info=True)
                results[etf_symbol] = {
                    "has_gap": False,
                    "gap_info": None,
                    "error": str(e)
                }
        
        return results
        
    except Exception as e:
        logger.error(f"检测ETF跳空失败: {e}", exc_info=True)
        return {}


def check_all_gaps_fillback(
    gap_results: Dict[str, Dict[str, Any]],
    config: Optional[Dict] = None
) -> Dict[str, Dict[str, Any]]:
    """
    检查所有已检测到的跳空是否回补（开盘后30分钟执行）
    
    Args:
        gap_results: 开盘时检测到的跳空结果（来自detect_etf_gaps_at_opening）
        config: 系统配置
    
    Returns:
        dict: {
            "510300": {
                "gap_info": {...},
                "fillback_result": {...},  # 回补检查结果
                "signal": {...}  # 如果生成信号
            },
            ...
        }
    """
    try:
        if config is None:
            config = load_system_config()
        
        etf_config = config.get('etf_trading', {})
        gap_config = etf_config.get('gap_strategy', {})
        
        if not gap_config.get('enabled', True):
            logger.debug("缺口策略未启用，跳过回补检查")
            return {}
        
        fillback_threshold = gap_config.get('fillback_threshold', 0.003)  # 默认0.3%
        min_signal_strength = gap_config.get('min_signal_strength', 0.6)  # 最低信号强度
        
        results: Dict[str, Dict[str, Any]] = {}
        
        for etf_symbol, gap_data in gap_results.items():
            if not gap_data.get("has_gap", False):
                continue
            
            gap_info = gap_data.get("gap_info")
            if gap_info is None:
                continue
            
            try:
                # 检查回补
                fillback_result = check_gap_fillback(
                    etf_symbol=etf_symbol,
                    gap_info=gap_info,
                    current_price=None,  # 自动获取
                    minute_data=None,  # 自动获取
                    fillback_threshold=fillback_threshold
                )
                
                # 如果回补且信号强度足够，生成信号
                signal = None
                if fillback_result.get("is_filled", False):
                    signal_strength = fillback_result.get("signal_strength", 0.0)
                    if signal_strength >= min_signal_strength:
                        signal = {
                            "signal_type": fillback_result.get("signal_type"),
                            "signal_strength": signal_strength,
                            "reason": fillback_result.get("reason"),
                            "etf_symbol": etf_symbol,
                            "current_price": fillback_result.get("current_price"),
                            "gap_type": gap_info.get("gap_type"),
                            "gap_pct": gap_info.get("gap_pct"),
                            "timestamp": datetime.now(pytz.timezone('Asia/Shanghai')).strftime("%Y-%m-%d %H:%M:%S")
                        }
                
                results[etf_symbol] = {
                    "gap_info": gap_info,
                    "fillback_result": fillback_result,
                    "signal": signal
                }
                
            except Exception as e:
                logger.error(f"检查ETF {etf_symbol} 跳空回补失败: {e}", exc_info=True)
                results[etf_symbol] = {
                    "gap_info": gap_info,
                    "fillback_result": None,
                    "signal": None,
                    "error": str(e)
                }
        
        return results
        
    except Exception as e:
        logger.error(f"检查所有跳空回补失败: {e}", exc_info=True)
        return {}
