""" 趋势分析插件 融合原系统 trend_analyzer.py 和 llm_enhancer.py OpenClaw 插件工具 """

import sys
import os
from typing import Optional, Dict, Any
from pathlib import Path

# 导入交易日判断工具
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
utils_path = os.path.join(parent_dir, 'utils')
if utils_path not in sys.path:
    sys.path.insert(0, utils_path)

try:
    from plugins.utils.trading_day import check_trading_day_before_operation
    TRADING_DAY_CHECK_AVAILABLE = True
except ImportError:
    TRADING_DAY_CHECK_AVAILABLE = False
    def check_trading_day_before_operation(*args, **kwargs):
        return None

# 尝试将当前环境中的本地 src 根目录加入 Python 路径
selected_root: Optional[Path] = None
for parent in Path(__file__).resolve().parents:
    if (parent / "src").exists():
        selected_root = parent
        break
if selected_root is not None and str(selected_root) not in sys.path:
    sys.path.insert(0, str(selected_root))

try:
    # 导入原系统的分析模块
    from src.trend_analyzer import (
        analyze_daily_market_after_close,
        analyze_market_before_open,
        analyze_opening_market
    )
    # 这些模块可能不存在，使用可选导入
    try:
        from src.llm_enhancer import enhance_with_llm
    except ImportError:
        enhance_with_llm = None
    
    try:
        from src.config_loader import load_system_config
    except ImportError:
        load_system_config = None
    
    try:
        from src.data_collection.index import fetch_index_opening_data
    except ImportError:
        fetch_index_opening_data = None
    
    ORIGINAL_SYSTEM_AVAILABLE = True
except ImportError as e:
    ORIGINAL_SYSTEM_AVAILABLE = False
    IMPORT_ERROR = str(e)

def trend_analysis(
    analysis_type: str = "after_close",  # "after_close", "before_open", "opening_market"
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    执行趋势分析（融合原系统逻辑和 LLM 增强）
    
    Args:
        analysis_type: 分析类型（"after_close", "before_open", "opening_market"）
        api_base_url: 原系统 API 基础地址（保留用于未来扩展）
        api_key: API Key（保留用于未来扩展）
    
    Returns:
        Dict: 包含分析结果和 LLM 增强的字典
    """
    try:
        # ========== 交易日判断（仅用于提示，不阻止执行） ==========
        # 注意：趋势分析基于历史数据，即使在非交易日也可以执行
        # 这里只做提示，不阻止执行
        if TRADING_DAY_CHECK_AVAILABLE:
            operation_name_map = {
                "after_close": "盘后分析",
                "before_open": "盘前分析",
                "opening_market": "开盘分析"
            }
            operation_name = operation_name_map.get(analysis_type, "趋势分析")
            trading_day_check = check_trading_day_before_operation(operation_name)
            if trading_day_check:
                # 非交易日时给出提示，但不阻止执行
                # 因为趋势分析可以使用历史数据，不依赖实时数据
                pass  # 允许继续执行，使用历史数据进行趋势分析
        # ========== 交易日判断结束 ==========
        
        # 加载原系统配置（如果可用）
        config = None
        if ORIGINAL_SYSTEM_AVAILABLE:
            try:
                config = load_system_config(use_cache=True)
            except Exception as e:
                pass  # 配置加载失败不影响主流程
        
        # 根据分析类型调用分析函数
        analysis_result = None
        if analysis_type == "after_close":
            # 盘后分析
            if ORIGINAL_SYSTEM_AVAILABLE:
                analysis_result = analyze_daily_market_after_close(config=config)
            else:
                return {
                    'success': False,
                    'message': '盘后分析需要原系统模块，当前不可用',
                    'data': None
                }
        elif analysis_type == "before_open":
            # 盘前分析
            if ORIGINAL_SYSTEM_AVAILABLE:
                analysis_result = analyze_market_before_open(config=config)
            else:
                return {
                    'success': False,
                    'message': '盘前分析需要原系统模块，当前不可用',
                    'data': None
                }
        elif analysis_type == "opening_market":
            # 开盘分析
            try:
                # 获取开盘数据
                opening_data_result = None
                if ORIGINAL_SYSTEM_AVAILABLE and fetch_index_opening_data is not None:
                    try:
                        opening_data_result = fetch_index_opening_data()
                    except Exception as e:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"原系统 fetch_index_opening_data 调用失败: {e}")
                        opening_data_result = None
                
                # 如果原系统获取失败，使用 OpenClaw 工具获取开盘数据（mode=test 避免 9:28 定时任务被交易日检查拦截）
                if not opening_data_result or not opening_data_result.get('success'):
                    try:
                        from plugins.data_collection.index.fetch_opening import fetch_index_opening

                        opening_data_result = fetch_index_opening(mode="test")
                    except Exception as e:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"OpenClaw fetch_index_opening 调用失败: {e}")
                
                if opening_data_result and opening_data_result.get('success'):
                    opening_data = opening_data_result.get('data', [])
                    
                    if ORIGINAL_SYSTEM_AVAILABLE and analyze_opening_market is not None:
                        try:
                            # 使用原系统分析
                            analysis_result = analyze_opening_market(
                                opening_data={item['code']: item for item in opening_data},
                                config=config
                            )
                        except Exception as e:
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.warning(f"原系统 analyze_opening_market 调用失败: {e}，使用简化版分析")
                            # 回退到简化版分析
                            analysis_result = _simple_opening_analysis(opening_data)
                    else:
                        # 简化版开盘分析（不依赖原系统）
                        analysis_result = _simple_opening_analysis(opening_data)
                else:
                    return {
                        'success': False,
                        'message': f'获取开盘数据失败：{opening_data_result.get("message", "Unknown error") if opening_data_result else "No data"}',
                        'data': None
                    }
            except Exception as e:
                import traceback
                return {
                    'success': False,
                    'message': f'开盘分析执行失败：{str(e)}',
                    'data': None,
                    'traceback': traceback.format_exc()
                }
        else:
            return {
                'success': False,
                'message': f'不支持的分析类型：{analysis_type}',
                'data': None
            }
        
        if analysis_result is None:
            return {
                'success': False,
                'message': '分析函数返回 None',
                'data': None
            }
        
        # ========== LLM 增强（使用原系统的 llm_enhancer）==========
        # 注意：原系统的分析函数内部可能已经调用了 LLM 增强
        # 如果分析结果中已经有 llm_summary，说明原系统已经增强过了
        # 如果没有，我们在这里进行增强
        if 'llm_summary' not in analysis_result:
            # 原系统函数没有进行 LLM 增强，我们在这里进行
            llm_summary = ""
            llm_meta = {}
            try:
                # 检查 LLM 增强是否启用
                llm_config = config.get('llm_enhancer', {}) if config else {}
                if llm_config.get('enabled', False):
                    # 检查该分析类型是否在启用列表中
                    enabled_types = llm_config.get('analysis_types', [])
                    if analysis_type in enabled_types:
                        # 调用原系统的 LLM 增强
                        llm_summary, llm_meta = enhance_with_llm(
                            analysis_data=analysis_result,
                            analysis_type=analysis_type,
                            config=config
                        )
                        # 将 LLM 增强结果添加到分析结果中
                        if llm_summary:
                            analysis_result['llm_summary'] = llm_summary
                        if llm_meta:
                            analysis_result['llm_meta'] = llm_meta
            except Exception as e:
                # LLM 增强失败不影响主流程
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"LLM 增强失败（不影响主流程）: {str(e)}")
        
        # 检查最终是否有 LLM 增强结果
        has_llm_enhancement = 'llm_summary' in analysis_result and analysis_result.get('llm_summary')
        
        # ========== 保存数据到文件（供仪表盘读取）==========
        # 在精简模式下，需要保存分析结果到文件，以便仪表盘可以读取显示
        try:
            from src.data_storage import save_trend_analysis
            
            # 保存趋势分析数据
            if save_trend_analysis(analysis_result, analysis_type=analysis_type, config=config):
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"趋势分析数据已保存到文件（供仪表盘读取）: {analysis_type}")
        except Exception as e:
            # 保存失败不影响主流程，只记录警告
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"保存趋势分析数据到文件失败（不影响分析功能）: {str(e)}")
        
        # ========== 返回结果 ==========
        return {
            'success': True,
            'message': f'{analysis_type} analysis completed',
            'data': analysis_result,
            'llm_enhanced': has_llm_enhancement
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }

# OpenClaw 工具函数接口
def tool_analyze_after_close() -> Dict[str, Any]:
    """OpenClaw 工具：盘后分析"""
    return trend_analysis(analysis_type="after_close")

def tool_analyze_before_open() -> Dict[str, Any]:
    """OpenClaw 工具：盘前分析"""
    return trend_analysis(analysis_type="before_open")

def _simple_opening_analysis(opening_data: list) -> Dict[str, Any]:
    """
    简化版开盘分析（不依赖原系统）
    
    Args:
        opening_data: 开盘数据列表，每项包含 name, code, open_price, close_yesterday, change_pct, volume
    
    Returns:
        dict: 分析结果
    """
    if not opening_data:
        return {
            'success': False,
            'message': '无开盘数据',
            'data': None
        }
    
    # 计算各指数分析
    index_analysis = {}
    strong_count = 0
    weak_count = 0
    
    for item in opening_data:
        code = item.get('code', 'unknown')
        name = item.get('name', 'Unknown')
        change_pct = item.get('change_pct', 0)
        volume = item.get('volume', 0)
        
        # 计算强度评分
        if change_pct > 1.0:
            strength = "强"
            strength_score = 0.8
            strong_count += 1
        elif change_pct > 0.3:
            strength = "偏强"
            strength_score = 0.5
            strong_count += 1
        elif change_pct > -0.3:
            strength = "中性"
            strength_score = 0.0
        elif change_pct > -1.0:
            strength = "偏弱"
            strength_score = -0.5
            weak_count += 1
        else:
            strength = "弱"
            strength_score = -0.8
            weak_count += 1
        
        index_analysis[code] = {
            'name': name,
            'change_pct': change_pct,
            'volume': volume,
            'strength': strength,
            'strength_score': strength_score
        }
    
    # 计算总体市场情绪
    total_count = strong_count + weak_count
    if total_count > 0:
        sentiment_score = (strong_count - weak_count) / total_count
    else:
        sentiment_score = 0
    
    if sentiment_score > 0.5:
        market_sentiment = "强势"
    elif sentiment_score > 0:
        market_sentiment = "偏强"
    elif sentiment_score > -0.5:
        market_sentiment = "中性"
    elif sentiment_score > -1:
        market_sentiment = "偏弱"
    else:
        market_sentiment = "弱势"
    
    return {
        'success': True,
        'data': {
            'indices': index_analysis,
            'summary': {
                'strong_count': strong_count,
                'weak_count': weak_count,
                'sentiment_score': sentiment_score,
                'market_sentiment': market_sentiment,
                'timestamp': opening_data[0].get('timestamp', '') if opening_data else ''
            }
        },
        'llm_summary': None,
        'llm_meta': None
    }

def tool_analyze_opening_market() -> Dict[str, Any]:
    """OpenClaw 工具：开盘分析"""
    return trend_analysis(analysis_type="opening_market")
