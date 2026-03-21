"""
技术指标计算插件
融合 Coze 插件 technical_indicators.py
OpenClaw 插件工具
"""

import math
from typing import Dict, Any, List, Optional
from datetime import datetime
import os

# 导入数据访问工具
import sys
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, parent_dir)

try:
    from plugins.data_access.read_cache_data import read_cache_data
except ImportError:
    # 如果导入失败，定义占位函数
    def read_cache_data(*args, **kwargs):
        return {'success': False, 'df': None, 'message': 'read_cache_data not available'}

# 导入缓存工具
utils_path = os.path.join(parent_dir, 'utils')
if utils_path not in sys.path:
    sys.path.insert(0, utils_path)

try:
    from plugins.utils.cache import cache_result
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False
    # 如果导入失败，定义占位装饰器
    def cache_result(*args, **kwargs):
        def decorator(func):
            return func
        return decorator


def _calculate_ma(closes: List[float]) -> Dict:
    """计算移动平均线（复用 Coze 插件逻辑）"""
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else None
    
    current = closes[-1]
    
    # 均线排列
    if ma5 > ma10 > ma20:
        arrangement = "多头排列"
    elif ma5 < ma10 < ma20:
        arrangement = "空头排列"
    else:
        arrangement = "交叉震荡"
    
    # 金叉死叉判断
    if len(closes) >= 6:
        prev_ma5 = sum(closes[-6:-1]) / 5
        prev_ma10 = sum(closes[-11:-1]) / 10
        
        if prev_ma5 <= prev_ma10 and ma5 > ma10:
            cross = "金叉"
        elif prev_ma5 >= prev_ma10 and ma5 < ma10:
            cross = "死叉"
        else:
            cross = "无"
    else:
        cross = "数据不足"
    
    return {
        "ma5": round(ma5, 4),
        "ma10": round(ma10, 4),
        "ma20": round(ma20, 4),
        "ma60": round(ma60, 4) if ma60 else None,
        "arrangement": arrangement,
        "cross_signal": cross,
        "price_vs_ma20": round((current / ma20 - 1) * 100, 2)
    }


def _calculate_macd(closes: List[float]) -> Dict:
    """计算MACD指标（复用 Coze 插件逻辑）"""
    # EMA计算
    def ema(data, period):
        multiplier = 2 / (period + 1)
        ema_values = [data[0]]
        for price in data[1:]:
            ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
        return ema_values
    
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    
    # DIF线
    dif = [ema12[i] - ema26[i] for i in range(len(closes))]
    
    # DEA线 (DIF的9日EMA)
    dea = ema(dif, 9)
    
    # MACD柱
    macd_hist = [(dif[i] - dea[i]) * 2 for i in range(len(closes))]
    
    current_dif = dif[-1]
    current_dea = dea[-1]
    current_macd = macd_hist[-1]
    
    # 信号判断
    if len(dif) >= 2:
        if dif[-2] <= dea[-2] and current_dif > current_dea:
            signal = "金叉"
        elif dif[-2] >= dea[-2] and current_dif < current_dea:
            signal = "死叉"
        elif current_macd > 0 and macd_hist[-2] < current_macd:
            signal = "红柱放大"
        elif current_macd < 0 and macd_hist[-2] > current_macd:
            signal = "绿柱放大"
        else:
            signal = "无明显信号"
    else:
        signal = "数据不足"
    
    return {
        "dif": round(current_dif, 4),
        "dea": round(current_dea, 4),
        "macd": round(current_macd, 4),
        "signal": signal
    }


def _calculate_rsi(closes: List[float], period: int = 14) -> Dict:
    """计算RSI指标（复用 Coze 插件逻辑）"""
    gains = []
    losses = []
    
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    if len(gains) < period:
        return {"error": "数据不足"}
    
    # 计算平均涨跌幅
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        rsi = 100
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
    
    # 信号判断
    if rsi > 80:
        signal = "超买"
        suggestion = "可能回调"
    elif rsi > 70:
        signal = "偏强"
        suggestion = "注意风险"
    elif rsi < 20:
        signal = "超卖"
        suggestion = "可能反弹"
    elif rsi < 30:
        signal = "偏弱"
        suggestion = "观察企稳"
    else:
        signal = "中性"
        suggestion = "正常区间"
    
    return {
        "rsi": round(rsi, 2),
        "period": period,
        "signal": signal,
        "suggestion": suggestion
    }


def _calculate_bollinger(closes: List[float], period: int = 20, std_dev: float = 2) -> Dict:
    """计算布林带（复用 Coze 插件逻辑）"""
    if len(closes) < period:
        return {"error": "数据不足"}
    
    # 中轨 (SMA)
    middle = sum(closes[-period:]) / period
    
    # 标准差
    variance = sum((p - middle) ** 2 for p in closes[-period:]) / period
    std = math.sqrt(variance)
    
    # 上下轨
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    
    current = closes[-1]
    
    # 带宽
    bandwidth = (upper - lower) / middle * 100
    
    # %B指标
    if upper != lower:
        percent_b = (current - lower) / (upper - lower)
    else:
        percent_b = 0.5
    
    # 信号判断
    if current > upper:
        signal = "突破上轨"
        suggestion = "可能超买或突破"
    elif current < lower:
        signal = "突破下轨"
        suggestion = "可能超卖或破位"
    elif percent_b > 0.8:
        signal = "接近上轨"
        suggestion = "注意压力"
    elif percent_b < 0.2:
        signal = "接近下轨"
        suggestion = "注意支撑"
    else:
        signal = "区间内"
        suggestion = "正常波动"
    
    return {
        "upper": round(upper, 4),
        "middle": round(middle, 4),
        "lower": round(lower, 4),
        "bandwidth": round(bandwidth, 2),
        "percent_b": round(percent_b, 4),
        "signal": signal,
        "suggestion": suggestion
    }


def _adapt_data_collection_output(price_data: Any, logger=None) -> List[Dict]:
    """适配数据采集插件的输出格式"""
    if isinstance(price_data, dict):
        if 'data' in price_data:
            data = price_data['data']
            if isinstance(data, dict) and 'klines' in data:
                return data['klines']
            elif isinstance(data, list):
                return data
        elif 'klines' in price_data:
            return price_data['klines']
    
    if isinstance(price_data, list):
        return price_data
    
    return []


@cache_result(cache_type="result", ttl=300)  # 缓存5分钟
def calculate_technical_indicators(
    symbol: str = "510300",
    data_type: str = "etf_daily",  # "index_daily", "etf_daily", "index_minute", "etf_minute"
    period: Optional[str] = None,  # 用于分钟数据
    indicators: List[str] = None,  # ["ma", "macd", "rsi", "bollinger"]
    lookback_days: int = 120,
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None,
    klines_data: Optional[List[Dict[str, Any]]] = None  # 直接传入的分钟K线数据（来自 tool_fetch_etf_minute）
) -> Dict[str, Any]:
    """
    计算技术指标（融合 Coze technical_indicators.py）
    
    Args:
        symbol: 标的代码
        data_type: 数据类型
        period: 周期（用于分钟数据）
        indicators: 需要计算的指标列表，默认全部计算
        lookback_days: 回看天数
        api_base_url: 原系统 API 基础地址
        api_key: API Key
        klines_data: 直接传入的分钟K线数据（来自 tool_fetch_etf_minute 的 klines），
                     传入时优先使用，绕过缓存读取。格式为 [{"time","open","close","high","low","volume",...}, ...]
    
    Returns:
        Dict: 包含技术指标计算结果的字典
    """
    try:
        from datetime import datetime, timedelta
        
        if indicators is None:
            indicators = ["ma", "macd", "rsi", "bollinger"]
        
        df = None
        
        # 优先使用直接传入的 klines 数据（工作流中步骤4->步骤5 数据传递）
        if klines_data and isinstance(klines_data, list) and len(klines_data) > 0:
            try:
                import pandas as pd
                df = pd.DataFrame(klines_data)
                # 统一列名：支持 open/close 或 开盘/收盘
                col_map = {'开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume'}
                for cn, en in col_map.items():
                    if cn in df.columns and en not in df.columns:
                        df[en] = df[cn]
                if 'close' not in df.columns and '收盘' in df.columns:
                    df['close'] = df['收盘']
            except Exception as e:
                pass  # 转换失败则回退到缓存读取
        
        # 若无直接数据，从缓存读取
        if df is None or df.empty:
            import pytz
            
            tz_shanghai = pytz.timezone('Asia/Shanghai')
            now = datetime.now(tz_shanghai)
            end_date = now.strftime('%Y%m%d')
            # 对于分钟数据，使用 lookback_days * 2 以确保包含非交易日（与 fetch_etf_minute 保持一致）
            if data_type in ['etf_minute', 'index_minute']:
                start_date = (now - timedelta(days=lookback_days * 2)).strftime('%Y%m%d')
            else:
                start_date = (now - timedelta(days=lookback_days)).strftime('%Y%m%d')
            
            cache_result = read_cache_data(
                data_type=data_type,
                symbol=symbol,
                period=period,
                start_date=start_date,
                end_date=end_date,
                return_df=True,
            )
            
            # 即使有 missing_dates，只要有数据就使用（部分缓存命中）
            if cache_result.get('df') is not None and not cache_result['df'].empty:
                df = cache_result['df']
            elif not cache_result.get('success', False):
                return {
                    'success': False,
                    'message': f"Failed to load data from cache: {cache_result.get('message', 'Unknown error')}",
                    'data': None
                }
            else:
                return {
                    'success': False,
                    'message': 'Failed to load data from cache: No data available',
                    'data': None
                }
        
        # 提取收盘价
        closes = []
        if 'close' in df.columns:
            closes = df['close'].tolist()
        elif '收盘' in df.columns:
            closes = df['收盘'].tolist()
        elif '收盘价' in df.columns:
            closes = df['收盘价'].tolist()
        else:
            # 尝试使用第一列数值列
            for col in df.columns:
                if df[col].dtype in ['float64', 'int64']:
                    closes = df[col].tolist()
                    break
        
        if len(closes) < 26:
            return {
                'success': False,
                'message': f'数据不足: {len(closes)} < 26，至少需要26条数据（当前有{len(closes)}条）',
                'data': None
            }
        
        result_data = {
            "symbol": symbol,
            "current_price": closes[-1],
            "indicators": {},
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # 计算各指标
        if "ma" in indicators:
            result_data["indicators"]["ma"] = _calculate_ma(closes)
        
        if "macd" in indicators:
            result_data["indicators"]["macd"] = _calculate_macd(closes)
        
        if "rsi" in indicators:
            result_data["indicators"]["rsi"] = _calculate_rsi(closes)
        
        if "bollinger" in indicators:
            result_data["indicators"]["bollinger"] = _calculate_bollinger(closes)
        
        # 生成综合信号
        result_data["signal"] = _generate_signal(result_data["indicators"])
        
        # 添加数据范围信息
        if not df.empty and '日期' in df.columns:
            start_date = df['日期'].iloc[0]
            end_date = df['日期'].iloc[-1]
            data_count = len(df)
            result_data["data_range"] = f"{start_date} 至 {end_date} ({data_count} 个交易日)"
        elif not df.empty and 'date' in df.columns:
            start_date = df['date'].iloc[0]
            end_date = df['date'].iloc[-1]
            data_count = len(df)
            result_data["data_range"] = f"{start_date} 至 {end_date} ({data_count} 个交易日)"
        
        # 格式化消息
        formatted_message = _format_indicators_message(result_data)
        
        return {
            "success": True,
            "data": result_data,
            "message": formatted_message,
            "source": "calculated"
        }
    
    except Exception as e:
        return {
            "success": False,
            "message": f"计算技术指标失败: {str(e)}",
            "data": None
        }


def _generate_signal(indicators: Dict) -> Dict:
    """生成综合信号（复用 Coze 插件逻辑）"""
    signals = []
    
    # MA信号
    if "ma" in indicators:
        ma = indicators["ma"]
        if ma.get("cross_signal") == "金叉":
            signals.append("均线金叉")
        elif ma.get("cross_signal") == "死叉":
            signals.append("均线死叉")
        if ma.get("arrangement") == "多头排列":
            signals.append("多头排列")
        elif ma.get("arrangement") == "空头排列":
            signals.append("空头排列")
    
    # MACD信号
    if "macd" in indicators:
        macd = indicators["macd"]
        signal = macd.get("signal", "")
        if "金叉" in signal:
            signals.append("MACD金叉")
        elif "死叉" in signal:
            signals.append("MACD死叉")
    
    # RSI信号
    if "rsi" in indicators:
        rsi = indicators["rsi"]
        signal = rsi.get("signal", "")
        if "超买" in signal:
            signals.append("RSI超买")
        elif "超卖" in signal:
            signals.append("RSI超卖")
    
    # 布林带信号
    if "bollinger" in indicators:
        boll = indicators["bollinger"]
        signal = boll.get("signal", "")
        if "突破上轨" in signal:
            signals.append("突破布林上轨")
        elif "突破下轨" in signal:
            signals.append("突破布林下轨")
    
    return {
        "signals": signals,
        "summary": ", ".join(signals) if signals else "无明显信号"
    }


def _format_indicators_message(result_data: Dict[str, Any]) -> str:
    """格式化技术指标结果为易读的消息"""
    if not result_data:
        return "数据为空"
    
    symbol = result_data.get("symbol", "N/A")
    current_price = result_data.get("current_price", 0)
    indicators = result_data.get("indicators", {})
    signal = result_data.get("signal", {})
    timestamp = result_data.get("timestamp", "")
    
    # 获取数据范围信息（如果有）
    data_range = ""
    if "data_range" in result_data:
        data_range = f"\n数据范围: {result_data['data_range']}"
    
    message = f"✅ 技术指标计算完成 - {symbol} ETF\n"
    message += f"当前价格: {current_price:.3f}\n"
    
    if data_range:
        message += data_range
    
    message += "\n📊 技术指标详情:\n"
    
    # RSI指标
    if "rsi" in indicators:
        rsi_data = indicators["rsi"]
        rsi_value = rsi_data.get("rsi", "N/A")
        rsi_signal = rsi_data.get("signal", "N/A")
        rsi_suggestion = rsi_data.get("suggestion", "")
        message += f"\n✅ RSI (相对强弱指标):\n"
        message += f"   RSI值: {rsi_value}\n"
        message += f"   状态: {rsi_signal}"
        if rsi_suggestion:
            message += f" ({rsi_suggestion})"
        message += "\n"
    
    # MACD指标
    if "macd" in indicators:
        macd_data = indicators["macd"]
        dif = macd_data.get("dif", "N/A")
        dea = macd_data.get("dea", "N/A")
        macd_value = macd_data.get("macd", "N/A")
        macd_signal = macd_data.get("signal", "N/A")
        message += f"\n✅ MACD (移动平均收敛发散):\n"
        message += f"   DIF: {dif}\n"
        message += f"   DEA: {dea}\n"
        message += f"   MACD柱: {macd_value}\n"
        message += f"   信号: {macd_signal}\n"
    
    # MA指标
    if "ma" in indicators:
        ma_data = indicators["ma"]
        ma5 = ma_data.get("ma5", "N/A")
        ma10 = ma_data.get("ma10", "N/A")
        ma20 = ma_data.get("ma20", "N/A")
        ma60 = ma_data.get("ma60", "N/A")
        arrangement = ma_data.get("arrangement", "N/A")
        cross_signal = ma_data.get("cross_signal", "N/A")
        price_vs_ma20 = ma_data.get("price_vs_ma20", "N/A")
        message += f"\n✅ MA (移动平均线):\n"
        message += f"   MA5: {ma5}\n"
        message += f"   MA10: {ma10}\n"
        message += f"   MA20: {ma20}\n"
        if ma60 != "N/A" and ma60 is not None:
            message += f"   MA60: {ma60}\n"
        message += f"   均线排列: {arrangement}\n"
        message += f"   交叉信号: {cross_signal}\n"
        if price_vs_ma20 != "N/A":
            message += f"   价格相对MA20: {price_vs_ma20}%\n"
    
    # ATR指标（如果计算了）
    if "atr" in indicators:
        atr_data = indicators["atr"]
        atr_value = atr_data.get("atr", "N/A")
        message += f"\n✅ ATR (平均真实波动幅度):\n"
        message += f"   ATR值: {atr_value}\n"
    
    # 布林带指标
    if "bollinger" in indicators:
        boll_data = indicators["bollinger"]
        upper = boll_data.get("upper", "N/A")
        middle = boll_data.get("middle", "N/A")
        lower = boll_data.get("lower", "N/A")
        bandwidth = boll_data.get("bandwidth", "N/A")
        percent_b = boll_data.get("percent_b", "N/A")
        boll_signal = boll_data.get("signal", "N/A")
        boll_suggestion = boll_data.get("suggestion", "")
        message += f"\n✅ BOLL (布林带):\n"
        message += f"   上轨: {upper}\n"
        message += f"   中轨: {middle}\n"
        message += f"   下轨: {lower}\n"
        message += f"   带宽: {bandwidth}%\n"
        message += f"   %B: {percent_b}\n"
        message += f"   信号: {boll_signal}"
        if boll_suggestion:
            message += f" ({boll_suggestion})"
        message += "\n"
    
    # 综合信号
    if signal:
        signal_summary = signal.get("summary", "无明显信号")
        message += f"\n📈 综合信号: {signal_summary}\n"
    
    if timestamp:
        message += f"\n⏰ 计算时间: {timestamp}\n"
    
    return message


# OpenClaw 工具函数接口
def tool_calculate_technical_indicators(
    symbol: str = "510300",
    data_type: str = "etf_daily",
    period: Optional[str] = None,
    indicators: Optional[List[str]] = None,
    lookback_days: int = 120,
    klines_data: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """OpenClaw 工具：计算技术指标。klines_data 可传入 tool_fetch_etf_minute 返回的 klines，用于工作流内数据传递。"""
    result = calculate_technical_indicators(
        symbol=symbol,
        data_type=data_type,
        period=period,
        indicators=indicators,
        lookback_days=lookback_days,
        klines_data=klines_data
    )
    
    # 如果成功，确保返回格式化消息
    if result.get("success") and result.get("message"):
        return result
    elif result.get("success") and result.get("data"):
        # 如果没有消息，生成一个
        formatted_message = _format_indicators_message(result.get("data"))
        result["message"] = formatted_message
        return result
    else:
        return result