"""
波动区间预测插件
融合原系统 on_demand_predictor.py 和 llm_enhancer.py
OpenClaw 插件工具
"""

import sys
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

# 尝试将当前环境中的本地 src 根目录加入 Python 路径
selected_root: Optional[Path] = None
for parent in Path(__file__).resolve().parents:
    if (parent / "src").exists():
        selected_root = parent
        break
if selected_root is not None and str(selected_root) not in sys.path:
    sys.path.insert(0, str(selected_root))

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

try:
    # 导入原系统的波动率预测模块
    from src.on_demand_predictor import (
        predict_index_volatility_range_on_demand,
        predict_etf_volatility_range_on_demand,
        predict_option_volatility_range_on_demand
    )
    from src.llm_enhancer import enhance_with_llm
    from src.config_loader import load_system_config
    ORIGINAL_SYSTEM_AVAILABLE = True
except ImportError as e:
    ORIGINAL_SYSTEM_AVAILABLE = False
    IMPORT_ERROR = str(e)


def _format_prediction_result(result: Dict[str, Any], result_type: str) -> str:
    """格式化预测结果为统一的文本格式（适合飞书和Chat显示）"""
    # 检查是否有错误（原系统函数可能返回 success=False 或包含 error 字段）
    if result.get('success') is False or 'error' in result:
        error_msg = result.get('error', result.get('message', '未知错误'))
        return f"❌ 预测失败\n\n错误信息: {error_msg}"
    
    # 使用表格格式，更结构化，减少AI二次处理
    reply = ""
    
    if result_type == 'option':
        contract_code = result.get('contract_code', 'N/A')
        strike_price = result.get('strike_price')
        option_type = result.get('option_type', 'call')
        option_type_name = '看涨' if option_type == 'call' else '看跌'
        underlying = result.get('underlying', 'N/A')
        
        reply = "## 📊 期权波动区间预测\n\n"
        reply += "**合约信息**\n"
        reply += f"- 合约代码: `{contract_code}`\n"
        reply += f"- 标的物: `{underlying}`\n"
        reply += f"- 期权类型: {option_type_name} (Call/Put)\n"
        if strike_price:
            reply += f"- 行权价: `{strike_price}`\n"
        reply += "\n"
    
    elif result_type == 'etf':
        symbol = result.get('symbol', 'N/A')
        symbol_name = result.get('symbol_name', symbol)
        reply = "## 📊 ETF波动区间预测\n\n"
        reply += "**标的物信息**\n"
        reply += f"- ETF代码: `{symbol}`\n"
        reply += f"- ETF名称: {symbol_name}\n"
        reply += "\n"
    
    elif result_type == 'index':
        symbol = result.get('symbol', 'N/A')
        symbol_name = result.get('symbol_name', symbol)
        reply = "## 📊 指数波动区间预测\n\n"
        reply += "**指数信息**\n"
        reply += f"- 指数代码: `{symbol}`\n"
        reply += f"- 指数名称: {symbol_name}\n"
        reply += "\n"
    
    # 使用表格格式展示关键数据
    reply += "### 关键指标\n\n"
    reply += "| 指标 | 数值 |\n"
    reply += "|------|------|\n"
    
    current_price = result.get('current_price')
    if current_price is not None:
        reply += f"| 当前价格 | {current_price:.4f} |\n"
    
    upper = result.get('upper')
    lower = result.get('lower')
    if upper is not None and lower is not None:
        reply += f"| 预测区间 | {lower:.4f} - {upper:.4f} |\n"
    
    range_pct = result.get('range_pct')
    if range_pct is not None:
        reply += f"| 波动范围 | {range_pct:.2f}% |\n"
    
    confidence = result.get('confidence')
    if confidence is not None:
        reply += f"| 置信度 | {confidence:.2f} |\n"
    
    # 期权特有信息
    if result_type == 'option':
        delta = result.get('delta')
        iv = result.get('iv')
        if delta is not None:
            reply += f"| Delta | {delta:.4f} |\n"
        if iv is not None:
            # 检查IV分位
            iv_percentile = result.get('iv_percentile')
            iv_warning = ""
            if iv_percentile is not None:
                if iv_percentile >= 90:
                    iv_warning = " ⚠️"
                elif iv_percentile <= 10:
                    iv_warning = " ✅"
            iv_text = f"{iv:.2f}%"
            if iv_percentile is not None:
                iv_text += f" ({iv_percentile:.0f}% 历史分位{iv_warning})"
            reply += f"| IV | {iv_text} |\n"
    
    # 技术指标
    rsi_value = result.get('rsi_value')
    rsi_status = result.get('rsi_status')
    if rsi_value is not None:
        rsi_status_text = f" ({rsi_status})" if rsi_status else ""
        reply += f"| RSI | {rsi_value:.2f}{rsi_status_text} |\n"
    
    # 流动性（期权特有）
    if result_type == 'option':
        liquidity = result.get('liquidity')
        if liquidity:
            liquidity_emoji = ""
            if liquidity == 'critical':
                liquidity_emoji = " 🚫"
            elif liquidity == 'poor':
                liquidity_emoji = " ⚠️"
            reply += f"| 流动性 | {liquidity}{liquidity_emoji} |\n"
    
    method = result.get('method')
    if method:
        reply += f"| 计算方法 | {method} |\n"
    
    remaining_minutes = result.get('remaining_minutes')
    if remaining_minutes is not None:
        reply += f"| 剩余交易时间 | {remaining_minutes}分钟 |\n"
    
    reply += "\n"
    
    # 当前位置分析
    position = result.get('position')
    position_desc = result.get('position_desc')
    trend_direction = result.get('trend_direction')
    if position is not None:
        reply += "### 📍 当前位置分析\n\n"
        position_pct = position * 100
        position_text = f"{position_pct:.1f}%"
        if position_desc:
            position_text += f" ({position_desc})"
        reply += f"- **区间位置**: {position_text}\n"
        if trend_direction:
            reply += f"- **趋势判断**: {trend_direction}\n"
        reply += "\n"
    
    # LLM增强结果（直接嵌入，不单独标记）
    llm_summary = result.get('llm_summary')
    if llm_summary:
        # LLM增强内容已经包含完整的分析，直接嵌入
        reply += "---\n\n"
        reply += llm_summary
        reply += "\n\n"
    
    timestamp = result.get('timestamp')
    if timestamp:
        reply += f"---\n\n*更新时间: {timestamp}*\n"
    
    return reply


def volatility_prediction(
    underlying: str = "510300",
    contract_codes: Optional[List[str]] = None,
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    预测波动区间（融合原系统逻辑和LLM增强）
    
    Args:
        underlying: 标的物代码（如 "510300" ETF 或 "000300" 指数）
        contract_codes: 期权合约代码列表（可选，如果提供则预测期权波动）
        api_base_url: 原系统 API 基础地址（保留用于未来扩展）
        api_key: API Key（保留用于未来扩展）
    
    Returns:
        Dict: 包含预测结果和LLM增强的字典，包含格式化的文本输出
    """
    try:
        # ========== 交易日判断（仅用于提示，不阻止执行） ==========
        # 注意：波动率预测基于历史数据，即使在非交易日也可以执行
        # 这里只做提示，不阻止执行
        if TRADING_DAY_CHECK_AVAILABLE:
            trading_day_check = check_trading_day_before_operation("波动率预测")
            if trading_day_check:
                # 非交易日时给出提示，但不阻止执行
                # 因为波动率预测可以使用历史数据，不依赖实时数据
                pass  # 允许继续执行，使用历史数据进行预测
        # ========== 交易日判断结束 ==========
        
        # 检查原系统模块是否可用
        if not ORIGINAL_SYSTEM_AVAILABLE:
            error_msg = f'原系统模块导入失败: {IMPORT_ERROR}'
            return {
                'success': False,
                'message': error_msg,
                'formatted_output': f"❌ {error_msg}",
                'data': None
            }
        
        # 加载原系统配置
        try:
            config = load_system_config(use_cache=True)
        except Exception as e:
            error_msg = f'加载原系统配置失败: {str(e)}'
            return {
                'success': False,
                'message': error_msg,
                'formatted_output': f"❌ {error_msg}",
                'data': None
            }
        
        # 判断预测类型并调用原系统函数
        prediction_results = []
        analysis_type = None
        
        if contract_codes and len(contract_codes) > 0:
            # 期权波动预测（支持多个合约代码）
            analysis_type = 'volatility_prediction_option'
            for contract_code in contract_codes:
                try:
                    prediction_result = predict_option_volatility_range_on_demand(
                        contract_code=contract_code,
                        config=config
                    )
                    # 检查结果是否有效（不是None且不是错误）
                    if prediction_result and prediction_result.get('success') is not False:
                        prediction_results.append(('option', prediction_result))
                    elif prediction_result and prediction_result.get('success') is False:
                        # 记录错误但继续处理其他合约
                        error_msg = prediction_result.get('error', '未知错误')
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"合约 {contract_code} 预测失败: {error_msg}")
                except Exception as e:
                    # 单个合约失败不影响其他合约
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"合约 {contract_code} 预测异常: {str(e)}")
        
        elif underlying.startswith('51') or underlying.startswith('159'):
            # ETF波动预测
            prediction_result = predict_etf_volatility_range_on_demand(
                symbol=underlying,
                config=config
            )
            if prediction_result:
                prediction_results.append(('etf', prediction_result))
            analysis_type = 'volatility_prediction_underlying'
        
        elif underlying.startswith('000') or underlying.startswith('399'):
            # 指数波动预测
            prediction_result = predict_index_volatility_range_on_demand(
                symbol=underlying,
                config=config
            )
            if prediction_result:
                prediction_results.append(('index', prediction_result))
            analysis_type = 'volatility_prediction_underlying'
        
        else:
            error_msg = f'不支持的标的物代码格式: {underlying}'
            return {
                'success': False,
                'message': error_msg,
                'formatted_output': f"❌ {error_msg}",
                'data': None
            }
        
        if not prediction_results:
            error_msg = '预测函数返回空结果'
            return {
                'success': False,
                'message': error_msg,
                'formatted_output': f"❌ {error_msg}",
                'data': None
            }
        
        # ========== LLM增强（使用原系统的llm_enhancer）==========
        # 注意：原系统的预测函数内部可能已经调用了LLM增强
        # 如果预测结果中已经有llm_summary，说明原系统已经增强过了
        # 如果没有，我们在这里进行增强
        
        for result_type, prediction_result in prediction_results:
            if 'llm_summary' not in prediction_result:
                # 原系统函数没有进行LLM增强，我们在这里进行
                llm_summary = ""
                llm_meta = {}
                
                try:
                    # 检查LLM增强是否启用
                    llm_config = config.get('llm_enhancer', {}) if config else {}
                    if llm_config.get('enabled', False):
                        # 检查该分析类型是否在启用列表中
                        # volatility_prediction_underlying 和 volatility_prediction_option 都匹配 volatility_prediction
                        enabled_types = llm_config.get('analysis_types', [])
                        is_enabled = analysis_type in enabled_types
                        if not is_enabled and analysis_type.startswith("volatility_prediction_"):
                            is_enabled = "volatility_prediction" in enabled_types
                        
                        if is_enabled:
                            # 调用原系统的LLM增强
                            llm_summary, llm_meta = enhance_with_llm(
                                analysis_data=prediction_result,
                                analysis_type=analysis_type,
                                config=config
                            )
                            
                            # 将LLM增强结果添加到预测结果中
                            if llm_summary:
                                prediction_result['llm_summary'] = llm_summary
                                if llm_meta:
                                    prediction_result['llm_meta'] = llm_meta
                except Exception as e:
                    # LLM增强失败不影响主流程
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"LLM增强失败（不影响主流程）: {str(e)}")
        
        # 格式化输出（统一格式，适合飞书和Chat显示）
        formatted_outputs = []
        for result_type, prediction_result in prediction_results:
            formatted_output = _format_prediction_result(prediction_result, result_type)
            formatted_outputs.append(formatted_output)
        
        # 如果有多个结果，用清晰的分隔符连接
        if len(formatted_outputs) > 1:
            # 添加总体标题
            final_formatted_output = "# 波动率预测结果\n\n"
            final_formatted_output += f"共 {len(formatted_outputs)} 个合约的预测结果：\n\n"
            final_formatted_output += "---\n\n".join(formatted_outputs)
        else:
            final_formatted_output = formatted_outputs[0] if formatted_outputs else ""
        
        # 检查最终是否有LLM增强结果
        has_llm_enhancement = any(
            'llm_summary' in result and result.get('llm_summary')
            for _, result in prediction_results
        )
        
        # ========== 保存数据到文件（供仪表盘读取）==========
        # 在精简模式下，需要保存数据到文件，以便仪表盘可以读取显示
        try:
            from src.data_storage import save_volatility_ranges
            from datetime import datetime
            import pytz
            
            # 构建波动区间数据结构（兼容原系统格式）
            tz_shanghai = pytz.timezone('Asia/Shanghai')
            now = datetime.now(tz_shanghai)
            
            # 根据预测结果类型构建数据结构
            if contract_codes and len(contract_codes) > 0:
                # 期权波动预测：构建多标的物格式
                volatility_ranges_data = {
                    'timestamp': now.strftime('%Y-%m-%d %H:%M:%S'),
                    'date': now.strftime('%Y%m%d'),
                    'underlyings': {}
                }
                
                # 按标的物分组期权预测结果
                for result_type, prediction_result in prediction_results:
                    if result_type == 'option':
                        # 从预测结果中提取标的物信息
                        underlying_from_result = prediction_result.get('underlying', underlying)
                        contract_code = prediction_result.get('contract_code', '')
                        option_type = prediction_result.get('option_type', 'call')
                        
                        if underlying_from_result not in volatility_ranges_data['underlyings']:
                            volatility_ranges_data['underlyings'][underlying_from_result] = {
                                'etf_range': None,  # ETF区间需要单独预测
                                'call_ranges': [],
                                'put_ranges': []
                            }
                        
                        # 构建期权区间数据
                        option_range = {
                            'contract_code': contract_code,
                            'strike_price': prediction_result.get('strike_price'),
                            'upper': prediction_result.get('upper'),
                            'lower': prediction_result.get('lower'),
                            'current_price': prediction_result.get('current_price'),
                            'range_pct': prediction_result.get('range_pct'),
                            'method': prediction_result.get('method'),
                            'confidence': prediction_result.get('confidence'),
                            'timestamp': prediction_result.get('timestamp', now.strftime('%Y-%m-%d %H:%M:%S'))
                        }
                        
                        if option_type == 'call':
                            volatility_ranges_data['underlyings'][underlying_from_result]['call_ranges'].append(option_range)
                        else:
                            volatility_ranges_data['underlyings'][underlying_from_result]['put_ranges'].append(option_range)
                
                # 保存波动区间数据
                save_volatility_ranges(volatility_ranges_data, config)
                import logging
                logger = logging.getLogger(__name__)
                logger.info("波动区间数据已保存到文件（供仪表盘读取）")
            else:
                # ETF或指数波动预测：构建单标的物格式
                main_result = prediction_results[0][1] if prediction_results else None
                if main_result:
                    result_type = prediction_results[0][0]
                    
                    if result_type == 'etf':
                        # ETF波动区间
                        volatility_ranges_data = {
                            'timestamp': now.strftime('%Y-%m-%d %H:%M:%S'),
                            'date': now.strftime('%Y%m%d'),
                            'underlyings': {
                                underlying: {
                                    'etf_range': {
                                        'symbol': underlying,
                                        'upper': main_result.get('upper'),
                                        'lower': main_result.get('lower'),
                                        'current_price': main_result.get('current_price'),
                                        'range_pct': main_result.get('range_pct'),
                                        'method': main_result.get('method'),
                                        'confidence': main_result.get('confidence'),
                                        'timestamp': main_result.get('timestamp', now.strftime('%Y-%m-%d %H:%M:%S'))
                                    },
                                    'call_ranges': [],
                                    'put_ranges': []
                                }
                            }
                        }
                    elif result_type == 'index':
                        # 指数波动区间
                        volatility_ranges_data = {
                            'timestamp': now.strftime('%Y-%m-%d %H:%M:%S'),
                            'date': now.strftime('%Y%m%d'),
                            'index_range': {
                                'symbol': underlying,
                                'upper': main_result.get('upper'),
                                'lower': main_result.get('lower'),
                                'current_price': main_result.get('current_price'),
                                'range_pct': main_result.get('range_pct'),
                                'method': main_result.get('method'),
                                'confidence': main_result.get('confidence'),
                                'timestamp': main_result.get('timestamp', now.strftime('%Y-%m-%d %H:%M:%S'))
                            }
                        }
                    else:
                        volatility_ranges_data = None
                    
                    if volatility_ranges_data:
                        save_volatility_ranges(volatility_ranges_data, config)
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.info("波动区间数据已保存到文件（供仪表盘读取）")
        except Exception as e:
            # 保存失败不影响主流程，只记录警告
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"保存波动区间数据到文件失败（不影响预测功能）: {str(e)}")
        
        # ========== 返回结果 ==========
        # 如果只有一个结果，直接返回该结果；如果有多个，返回第一个作为主要结果
        main_result = prediction_results[0][1] if prediction_results else None
        
        return {
            'success': True,
            'message': 'Volatility prediction completed',
            'formatted_output': final_formatted_output,
            'data': main_result,
            'all_results': [result for _, result in prediction_results] if len(prediction_results) > 1 else None,
            'llm_enhanced': has_llm_enhancement
        }
    
    except Exception as e:
        error_msg = f'Error: {str(e)}'
        return {
            'success': False,
            'message': error_msg,
            'formatted_output': f"❌ {error_msg}",
            'data': None
        }


# OpenClaw 工具函数接口
def tool_predict_volatility(
    underlying: str = "510300",
    contract_codes: Optional[List[str]] = None
) -> str:
    """
    OpenClaw 工具：预测波动区间
    
    支持：
    - ETF波动预测：underlying="510300"
    - 指数波动预测：underlying="000300"
    - 期权波动预测：contract_codes=["10010891", "10010892"]（支持多个合约）
    
    返回格式与其他工具保持一致，适合在飞书群组中显示
    """
    try:
        result = volatility_prediction(underlying=underlying, contract_codes=contract_codes)
        
        # 确保有格式化的输出
        if result.get('success'):
            output = result.get('formatted_output', '')
            # 如果输出为空，尝试从data中格式化
            if not output and result.get('data'):
                # 尝试从data中提取信息并格式化
                data = result.get('data', {})
                if isinstance(data, dict):
                    # 判断类型并格式化
                    if 'contract_code' in data:
                        output = _format_prediction_result(data, 'option')
                    elif data.get('type') == 'etf' or (underlying.startswith('51') or underlying.startswith('159')):
                        output = _format_prediction_result(data, 'etf')
                    elif data.get('type') == 'index' or (underlying.startswith('000') or underlying.startswith('399')):
                        output = _format_prediction_result(data, 'index')
                    else:
                        output = f"预测完成，但无法格式化结果。原始数据：{str(data)[:200]}"
            
            # 直接返回格式化的文本字符串，供OpenClaw在飞书中直接显示
            formatted_message = output if output else "预测完成，但未生成输出内容"
            
            # 限制消息长度，避免过长导致问题（飞书消息可能有长度限制）
            max_message_length = 2000  # 飞书消息建议长度
            if len(formatted_message) > max_message_length:
                formatted_message = formatted_message[:max_message_length] + "\n\n...（内容过长，已截断）"
            
            return formatted_message
        else:
            # 返回错误信息（字符串格式）
            error_msg = result.get('formatted_output') or result.get('message', '预测失败')
            return error_msg if error_msg else "预测失败，未知错误"
    
    except Exception as e:
        # 捕获所有异常，返回友好的错误信息（字符串格式）
        error_detail = str(e)
        return f"❌ 预测失败\n\n错误信息: {error_detail}\n\n请检查参数是否正确，或联系管理员查看日志。"
