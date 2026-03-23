"""
盘口数据获取器
从AKShare获取期权实时盘口数据（买卖价、买卖量等）
"""

import akshare as ak
from typing import Dict, Optional, Any

from src.logger_config import get_module_logger, log_error_with_context

logger = get_module_logger(__name__)


class OptionMarketDataFetcher:
    """期权市场数据获取器"""
    
    def __init__(self):
        """初始化"""
        pass
    
    def fetch_realtime_quotes(self, contract_code: str) -> Optional[Dict[str, Any]]:
        """
        获取期权实时盘口数据
        
        注意：此接口仅支持上交所（SSE）期权，不支持深交所（SZSE）期权。
        深交所期权需要使用其他数据源（如Tushare）。
        
        Args:
            contract_code: 期权合约代码（如 "10010467"，上交所期权）
        
        Returns:
            dict: 盘口数据，包含：
                - bid_price: 买一价
                - bid_volume: 买一量
                - ask_price: 卖一价
                - ask_volume: 卖一量
                - last_price: 最新价
                - volume: 成交量
                如果失败返回None
        """
        try:
            logger.debug(f"获取期权实时盘口数据: {contract_code}")
            
            # 使用AKShare获取期权实时数据
            spot_data = ak.option_sse_spot_price_sina(symbol=contract_code)
            
            if spot_data is None or spot_data.empty:
                logger.warning(f"未获取到期权实时数据: {contract_code}")
                return None
            
            # 将DataFrame转换为字典，方便查找
            data_dict = {}
            for idx, row in spot_data.iterrows():
                field = row.get('字段', '')
                value = row.get('值', '')
                if field and value:
                    data_dict[str(field).strip()] = str(value).strip()
            
            # 调试：输出所有字段名（仅在DEBUG级别）
            if logger.isEnabledFor(10):  # DEBUG level
                logger.debug(f"获取到的字段列表: {list(data_dict.keys())}")
            
            # 提取关键字段（尝试多种可能的字段名）
            quotes = {}
            
            # 买一价：尝试多种可能的字段名
            bid_price_str = None
            for key in ['买一价', '买一', '买1价', '买1', 'bid1', 'bid_price', '买入价', '买价']:
                if key in data_dict:
                    bid_price_str = data_dict[key]
                    break
            
            # 买一量：尝试多种可能的字段名
            bid_volume_str = None
            for key in ['买一量', '买一量(手)', '买1量', '买1量(手)', 'bid1_volume', 'bid_volume', '买入量', '买量']:
                if key in data_dict:
                    bid_volume_str = data_dict[key]
                    break
            
            # 卖一价：尝试多种可能的字段名
            ask_price_str = None
            for key in ['卖一价', '卖一', '卖1价', '卖1', 'ask1', 'ask_price', '卖出价', '卖价']:
                if key in data_dict:
                    ask_price_str = data_dict[key]
                    break
            
            # 卖一量：尝试多种可能的字段名
            ask_volume_str = None
            for key in ['卖一量', '卖一量(手)', '卖1量', '卖1量(手)', 'ask1_volume', 'ask_volume', '卖出量', '卖量']:
                if key in data_dict:
                    ask_volume_str = data_dict[key]
                    break
            
            # 最新价：尝试多种可能的字段名
            last_price_str = None
            for key in ['最新价', '当前价', '现价', 'last_price', 'price', '成交价', '最新成交价']:
                if key in data_dict:
                    last_price_str = data_dict[key]
                    break
            
            # 成交量：尝试多种可能的字段名
            volume_str = None
            for key in ['成交量', '成交量(手)', 'volume', '成交总量', '总成交量']:
                if key in data_dict:
                    volume_str = data_dict[key]
                    break
            
            # 转换为数值
            try:
                quotes['bid_price'] = float(bid_price_str) if bid_price_str else None
                quotes['bid_volume'] = int(float(bid_volume_str)) if bid_volume_str else 0
                quotes['ask_price'] = float(ask_price_str) if ask_price_str else None
                quotes['ask_volume'] = int(float(ask_volume_str)) if ask_volume_str else 0
                quotes['last_price'] = float(last_price_str) if last_price_str else None
                quotes['volume'] = int(float(volume_str)) if volume_str else 0
            except (ValueError, TypeError) as e:
                logger.warning(f"解析盘口数据失败: {e}, 数据: {data_dict}")
                return None
            
            # 验证数据有效性
            # 如果无法获取买卖价，尝试使用最新价作为fallback（但标记为估算值）
            if quotes['bid_price'] is None or quotes['ask_price'] is None:
                if quotes['last_price'] is not None and quotes['last_price'] > 0:
                    # 使用最新价估算买卖价（假设价差为2%）
                    estimated_spread = quotes['last_price'] * 0.01  # 1%的价差
                    quotes['bid_price'] = quotes['last_price'] - estimated_spread
                    quotes['ask_price'] = quotes['last_price'] + estimated_spread
                    quotes['is_estimated'] = True  # 标记为估算值
                    logger.warning(f"无法获取盘口数据，使用最新价估算: last_price={quotes['last_price']:.4f}, "
                                 f"估算bid={quotes['bid_price']:.4f}, ask={quotes['ask_price']:.4f}")
                else:
                    logger.warning(f"盘口数据不完整且无最新价: bid_price={quotes['bid_price']}, "
                                 f"ask_price={quotes['ask_price']}, last_price={quotes['last_price']}")
                    logger.debug(f"可用字段: {list(data_dict.keys())}")
                    return None
            else:
                quotes['is_estimated'] = False
            
            bid_price = quotes.get('bid_price')
            ask_price = quotes.get('ask_price')
            if bid_price is None or ask_price is None:
                return None
            
            if bid_price <= 0 or ask_price <= 0:
                logger.warning(f"盘口价格无效: bid_price={bid_price}, ask_price={ask_price}")
                return None
            
            if ask_price < bid_price:
                logger.warning(f"盘口价格异常: 卖一价({ask_price}) < 买一价({bid_price})")
                # 修正：交换买卖价
                quotes['bid_price'], quotes['ask_price'] = ask_price, bid_price
                quotes['bid_volume'], quotes['ask_volume'] = quotes['ask_volume'], quotes['bid_volume']
            
            logger.debug(f"获取到盘口数据: bid={quotes['bid_price']}, ask={quotes['ask_price']}, "
                        f"bid_vol={quotes['bid_volume']}, ask_vol={quotes['ask_volume']}")
            
            return quotes
            
        except Exception as e:
            log_error_with_context(
                logger, e,
                {'function': 'fetch_realtime_quotes', 'contract_code': contract_code},
                "获取期权实时盘口数据失败"
            )
            return None
    
    def calculate_market_metrics(self, quotes: Dict[str, Any]) -> Dict[str, Any]:
        """
        计算市场指标
        
        Args:
            quotes: 盘口数据
        
        Returns:
            dict: 市场指标，包含：
                - spread: 买卖价差（绝对差值）
                - spread_pct: 买卖价差百分比
                - mid_price: 中间价
                - depth_imbalance: 深度不平衡度（0-1，0表示完全平衡）
                - total_depth: 总深度（买卖量之和）
        """
        try:
            bid_price = quotes.get('bid_price', 0)
            ask_price = quotes.get('ask_price', 0)
            bid_volume = quotes.get('bid_volume', 0)
            ask_volume = quotes.get('ask_volume', 0)
            
            if bid_price <= 0 or ask_price <= 0:
                logger.warning("盘口价格无效，无法计算市场指标")
                return {
                    'spread': 0,
                    'spread_pct': 0,
                    'mid_price': 0,
                    'depth_imbalance': 0,
                    'total_depth': 0
                }
            
            # 计算买卖价差
            spread = ask_price - bid_price
            mid_price = (bid_price + ask_price) / 2.0
            spread_pct = (spread / mid_price * 100) if mid_price > 0 else 0
            
            # 计算深度不平衡度
            total_depth = bid_volume + ask_volume
            if total_depth > 0:
                depth_imbalance = abs(bid_volume - ask_volume) / total_depth
            else:
                depth_imbalance = 0.5  # 无深度时，认为不平衡
            
            metrics = {
                'spread': round(spread, 4),
                'spread_pct': round(spread_pct, 2),
                'mid_price': round(mid_price, 4),
                'depth_imbalance': round(depth_imbalance, 3),
                'total_depth': total_depth,
                'is_estimated': quotes.get('is_estimated', False)  # 传递估算标志
            }
            
            logger.debug(f"市场指标: 价差={spread_pct:.2f}%, 深度不平衡={depth_imbalance:.3f}, 总深度={total_depth}")
            
            return metrics
            
        except Exception as e:
            log_error_with_context(
                logger, e,
                {'function': 'calculate_market_metrics', 'quotes': quotes},
                "计算市场指标失败"
            )
            return {
                'spread': 0,
                'spread_pct': 0,
                'mid_price': 0,
                'depth_imbalance': 0,
                'total_depth': 0
            }
