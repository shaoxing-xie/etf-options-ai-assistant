"""
GARCH参数自动优化模块
实现GARCH模型参数的自动优化和缓存
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Any
from pathlib import Path
import json
from datetime import datetime
import pytz
import warnings

from src.logger_config import get_module_logger

logger = get_module_logger(__name__)

# GARCH参数缓存路径
GARCH_PARAMS_CACHE_DIR = Path("data/garch_params_cache")
GARCH_PARAMS_CACHE_FILE = GARCH_PARAMS_CACHE_DIR / "optimal_params.json"

try:
    from arch import arch_model
    from statsmodels.tsa.arima.model import ARIMA
    ARCH_AVAILABLE = True
    ARIMA_AVAILABLE = True
except ImportError as e:
    ARCH_AVAILABLE = False
    ARIMA_AVAILABLE = False
    logger.warning(f"arch或statsmodels库未安装，GARCH优化功能将不可用: {e}")


def optimize_garch_parameters(
    price_series: pd.Series,
    max_p: int = 2,
    max_q: int = 2,
    max_arima_p: int = 2,
    max_arima_d: int = 2,
    max_arima_q: int = 2,
    use_cache: bool = True,
    symbol: str = '000300'
) -> Dict[str, Any]:
    """
    使用AIC/BIC准则自动选择最优GARCH参数
    
    Args:
        price_series: 价格序列
        max_p, max_q: GARCH模型的最大p、q值
        max_arima_p, max_arima_d, max_arima_q: ARIMA模型的最大参数值
        use_cache: 是否使用缓存
        symbol: 标的代码（用于缓存键）
    
    Returns:
        dict: 最优参数 {'garch_p': 1, 'garch_q': 1, 'arima_order': (1, 1, 1), 'aic': 1234.56}
    """
    if not ARCH_AVAILABLE or not ARIMA_AVAILABLE:
        logger.warning("GARCH库未安装，返回默认参数")
        return {
            'garch_p': 1,
            'garch_q': 1,
            'arima_order': (1, 1, 1),
            'aic': None,
            'bic': None
        }
    
    try:
        # 检查缓存
        if use_cache:
            cached_params = _load_cached_params(symbol)
            if cached_params:
                logger.debug(f"使用缓存的GARCH参数: {cached_params}")
                return cached_params
        
        if len(price_series) < 50:
            logger.warning(f"价格序列长度不足（{len(price_series)} < 50），使用默认参数")
            return {
                'garch_p': 1,
                'garch_q': 1,
                'arima_order': (1, 1, 1),
                'aic': None,
                'bic': None
            }
        
        # 计算对数收益率
        returns = np.diff(np.log(price_series.values + 1e-6))
        returns_series = pd.Series(returns, index=price_series.index[1:])
        
        best_aic = float('inf')
        best_params = {
            'garch_p': 1,
            'garch_q': 1,
            'arima_order': (1, 1, 1),
            'aic': None,
            'bic': None
        }
        
        # 限制搜索范围（避免计算时间过长）
        # 只搜索常用的参数组合
        common_combinations = [
            (1, 1, (1, 1, 1)),
            (1, 1, (0, 1, 1)),
            (1, 1, (1, 1, 0)),
            (1, 1, (2, 1, 1)),
            (2, 1, (1, 1, 1)),
            (1, 2, (1, 1, 1)),
            (2, 2, (1, 1, 1)),
        ]
        
        # 网格搜索
        for p, q, arima_order in common_combinations:
            if p > max_p or q > max_q:
                continue
            
            ar_p, ar_d, ar_q = arima_order
            if ar_p > max_arima_p or ar_d > max_arima_d or ar_q > max_arima_q:
                continue
            
            try:
                # 拟合ARIMA模型
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    arima_model = ARIMA(returns_series, order=arima_order)
                    arima_fit = arima_model.fit()
                    arima_resid = arima_fit.resid
                
                # 拟合GARCH模型
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    garch_model = arch_model(arima_resid, vol='GARCH', p=p, q=q, dist='normal')
                    garch_fit = garch_model.fit(disp='off')
                    
                    aic = garch_fit.aic
                    bic = garch_fit.bic
                    
                    # 使用AIC作为主要准则，BIC作为辅助
                    if aic < best_aic:
                        best_aic = aic
                        best_params = {
                            'garch_p': p,
                            'garch_q': q,
                            'arima_order': arima_order,
                            'aic': aic,
                            'bic': bic
                        }
                        
            except Exception as e:
                logger.debug(f"参数 ({p},{q},{arima_order}) 拟合失败: {e}")
                continue
        
        # 保存到缓存
        if use_cache:
            _save_cached_params(symbol, best_params)
        
        logger.info(f"GARCH参数优化完成: {best_params}")
        return best_params
        
    except Exception as e:
        logger.error(f"GARCH参数优化失败: {e}", exc_info=True)
        return {
            'garch_p': 1,
            'garch_q': 1,
            'arima_order': (1, 1, 1),
            'aic': None,
            'bic': None
        }


def _load_cached_params(symbol: str) -> Optional[Dict[str, Any]]:
    """从缓存加载GARCH参数"""
    try:
        if not GARCH_PARAMS_CACHE_FILE.exists():
            return None
        
        with open(GARCH_PARAMS_CACHE_FILE, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        
        # 检查缓存是否过期（7天）
        if symbol in cache:
            cached_data = cache[symbol]
            cached_time = datetime.fromisoformat(cached_data.get('timestamp', ''))
            if (datetime.now(pytz.timezone('Asia/Shanghai')) - cached_time).days < 7:
                return cached_data.get('params')
        
        return None
        
    except Exception as e:
        logger.warning(f"加载GARCH参数缓存失败: {e}")
        return None


def _save_cached_params(symbol: str, params: Dict[str, Any]):
    """保存GARCH参数到缓存"""
    try:
        GARCH_PARAMS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        
        # 读取现有缓存
        if GARCH_PARAMS_CACHE_FILE.exists():
            with open(GARCH_PARAMS_CACHE_FILE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
        else:
            cache = {}
        
        # 更新缓存
        cache[symbol] = {
            'params': params,
            'timestamp': datetime.now(pytz.timezone('Asia/Shanghai')).isoformat()
        }
        
        # 保存
        with open(GARCH_PARAMS_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        
    except Exception as e:
        logger.warning(f"保存GARCH参数缓存失败: {e}")
