"""
Prophet模型
用于ETF趋势预测
"""

import pandas as pd
from typing import Dict, Any
from src.logger_config import get_module_logger

logger = get_module_logger(__name__)

try:
    from prophet import Prophet
    PROPHET_AVAILABLE = True
except ImportError:
    PROPHET_AVAILABLE = False
    logger.warning("Prophet库未安装，Prophet模型将不可用。请运行: pip install prophet")


class ProphetETFModel:
    """Prophet ETF模型"""
    
    def __init__(self):
        """
        初始化Prophet模型
        
        使用默认参数（后续根据回测优化）：
        - yearly_seasonality=False: 不启用年度季节性（ETF数据通常不需要）
        - weekly_seasonality=True: 启用周季节性（捕捉周内模式）
        - daily_seasonality=True: 启用日季节性（捕捉日内模式）
        - changepoint_prior_scale=0.05: 变化点先验尺度（较小值使趋势变化更平滑）
        - seasonality_prior_scale=10: 季节性先验尺度（默认值）
        """
        if not PROPHET_AVAILABLE:
            raise ImportError("Prophet库未安装，无法使用Prophet模型")
        
        self.model = Prophet(
            yearly_seasonality=False,
            weekly_seasonality=True,
            daily_seasonality=True,
            changepoint_prior_scale=0.05,  # 默认参数
            seasonality_prior_scale=10     # 默认参数
        )
    
    def predict_trend(
        self,
        etf_daily_data: pd.DataFrame,
        forecast_days: int = 5
    ) -> Dict[str, Any]:
        """
        预测ETF趋势方向
        
        Args:
            etf_daily_data: ETF日线数据（必须包含'收盘'列，索引为日期）
            forecast_days: 预测天数（默认5天）
        
        Returns:
            dict: {
                'direction': 'up' | 'down' | 'neutral',
                'confidence': float,  # 基于预测区间宽度
                'forecast_prices': list,  # 预测价格列表
                'forecast_upper': list,  # 预测上界
                'forecast_lower': list,  # 预测下界
                'current_price': float,  # 当前价格
                'forecast_change_pct': float  # 预测变化百分比
            }
        """
        try:
            if not PROPHET_AVAILABLE:
                return {
                    'direction': 'neutral',
                    'confidence': 0.5,
                    'forecast_prices': [],
                    'forecast_upper': [],
                    'forecast_lower': [],
                    'error': 'Prophet库未安装'
                }
            
            if etf_daily_data is None or etf_daily_data.empty:
                logger.warning("ETF日线数据为空，无法进行Prophet预测")
                return {
                    'direction': 'neutral',
                    'confidence': 0.5,
                    'forecast_prices': [],
                    'forecast_upper': [],
                    'forecast_lower': [],
                    'error': '数据为空'
                }
            
            # 检查必要的列
            if '收盘' not in etf_daily_data.columns:
                logger.warning("ETF日线数据缺少'收盘'列，无法进行Prophet预测")
                return {
                    'direction': 'neutral',
                    'confidence': 0.5,
                    'forecast_prices': [],
                    'forecast_upper': [],
                    'forecast_lower': [],
                    'error': '缺少收盘价列'
                }
            
            # 准备Prophet数据格式（需要'ds'和'y'列）
            # ds: 日期（datetime类型），y: 价格
            prophet_df = pd.DataFrame({
                'ds': pd.to_datetime(etf_daily_data.index),
                'y': etf_daily_data['收盘'].values
            })
            
            # 确保数据按日期排序
            prophet_df = prophet_df.sort_values('ds').reset_index(drop=True)
            
            # 训练模型
            logger.debug(f"开始训练Prophet模型，数据量: {len(prophet_df)}")
            self.model.fit(prophet_df)
            
            # 创建未来日期
            future = self.model.make_future_dataframe(periods=forecast_days)
            
            # 预测
            forecast = self.model.predict(future)
            
            # 提取预测结果（最后forecast_days天的数据）
            forecast_tail = forecast.tail(forecast_days)
            
            # 获取当前价格（最后一个历史数据点）
            current_price = etf_daily_data['收盘'].iloc[-1]
            
            # 获取预测价格（最后一天的预测值）
            forecast_price = forecast_tail['yhat'].iloc[-1]
            forecast_upper = forecast_tail['yhat_upper'].iloc[-1]
            forecast_lower = forecast_tail['yhat_lower'].iloc[-1]
            
            # 计算预测变化百分比
            forecast_change_pct = (forecast_price - current_price) / current_price
            
            # 计算置信度（基于预测区间宽度）
            confidence = self._calculate_confidence(
                forecast_upper,
                forecast_lower,
                current_price
            )
            
            # 确定方向
            # 如果预测价格 > 当前价格 * 1.01（1%涨幅），则为上涨
            # 如果预测价格 < 当前价格 * 0.99（1%跌幅），则为下跌
            # 否则为中性
            if forecast_change_pct > 0.01:
                direction = 'up'
            elif forecast_change_pct < -0.01:
                direction = 'down'
            else:
                direction = 'neutral'
            
            return {
                'direction': direction,
                'confidence': confidence,
                'forecast_prices': forecast_tail['yhat'].tolist(),
                'forecast_upper': forecast_tail['yhat_upper'].tolist(),
                'forecast_lower': forecast_tail['yhat_lower'].tolist(),
                'current_price': current_price,
                'forecast_price': forecast_price,
                'forecast_change_pct': forecast_change_pct
            }
            
        except Exception as e:
            logger.error(f"Prophet预测ETF趋势失败: {e}", exc_info=True)
            return {
                'direction': 'neutral',
                'confidence': 0.5,
                'forecast_prices': [],
                'forecast_upper': [],
                'forecast_lower': [],
                'error': str(e)
            }
    
    def _calculate_confidence(
        self,
        forecast_upper: float,
        forecast_lower: float,
        current_price: float
    ) -> float:
        """
        计算置信度（基于预测区间宽度）
        
        规则：
        - 预测区间宽度越小，置信度越高
        - 预测区间宽度 = (upper - lower) / current_price
        - 置信度 = 1 / (1 + 预测区间宽度 * 10)
        
        示例：
        - 预测区间宽度 = 0.02 (2%) → 置信度 = 1 / (1 + 0.02*10) = 0.83
        - 预测区间宽度 = 0.05 (5%) → 置信度 = 1 / (1 + 0.05*10) = 0.67
        
        Args:
            forecast_upper: 预测上界
            forecast_lower: 预测下界
            current_price: 当前价格
        
        Returns:
            float: 置信度 (0-1)
        """
        try:
            if current_price <= 0:
                return 0.5
            
            interval_width = (forecast_upper - forecast_lower) / current_price
            confidence = 1 / (1 + interval_width * 10)
            
            # 限制在0-1范围内
            return max(0.0, min(1.0, confidence))
            
        except Exception as e:
            logger.warning(f"计算Prophet置信度失败: {e}，使用默认值0.5")
            return 0.5
