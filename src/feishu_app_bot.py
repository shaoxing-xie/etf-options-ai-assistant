"""
飞书应用机器人模块（支持双向通信）
使用飞书开放平台API，支持接收和发送消息
"""

import requests
import json
import hmac
import hashlib
import base64
import time
from typing import Dict, Optional, Any, Callable
from datetime import datetime
import pytz

from src.logger_config import get_module_logger, log_error_with_context
from src.config_loader import load_system_config

logger = get_module_logger(__name__)


class FeishuAppBot:
    """飞书应用机器人（支持双向通信）"""
    
    def __init__(self, config: Optional[Dict] = None):
        """
        初始化飞书应用机器人
        
        Args:
            config: 系统配置，如果为None则自动加载
        """
        if config is None:
            config = load_system_config()
        
        self.config = config
        notification_config = config.get('notification', {})
        feishu_config = notification_config.get('feishu_app', {})
        
        # 应用凭证
        self.app_id = feishu_config.get('app_id')
        self.app_secret = feishu_config.get('app_secret')
        
        # 加密配置（用于验证webhook请求）
        self.encrypt_key = feishu_config.get('encrypt_key', '')
        
        # API基础URL
        self.base_url = "https://open.feishu.cn/open-apis"
        
        # 访问令牌缓存
        self._access_token = None
        self._token_expires_at = 0
        
        # 消息处理器
        self.message_handlers: Dict[str, Callable] = {}
        
        if not self.app_id or not self.app_secret:
            logger.warning("飞书应用凭证未配置，双向通信功能不可用")
    
    def get_access_token(self) -> Optional[str]:
        """
        获取访问令牌（tenant_access_token）
        
        Returns:
            str: 访问令牌，如果获取失败返回None
        """
        try:
            # 检查缓存
            if self._access_token and time.time() < self._token_expires_at:
                return self._access_token
            
            url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
            payload = {
                "app_id": self.app_id,
                "app_secret": self.app_secret
            }
            
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            if result.get("code") == 0:
                self._access_token = result.get("tenant_access_token")
                # 令牌有效期通常是2小时，提前5分钟刷新
                expire = result.get("expire", 7200)
                self._token_expires_at = time.time() + expire - 300
                logger.debug("飞书访问令牌获取成功")
                return self._access_token
            else:
                logger.error(f"获取飞书访问令牌失败: {result.get('msg')}")
                return None
                
        except Exception as e:
            log_error_with_context(
                logger, e,
                {'function': 'get_access_token'},
                "获取飞书访问令牌失败"
            )
            return None
    
    def send_message(
        self,
        receive_id: str,
        receive_id_type: str = "chat_id",
        message_type: str = "text",
        content: Dict[str, Any] = None,
        title: Optional[str] = None
    ) -> bool:
        """
        发送消息到飞书群或个人
        
        Args:
            receive_id: 接收者ID（群ID或用户ID）
            receive_id_type: 接收者类型，"chat_id"（群）或"user_id"（用户）
            message_type: 消息类型，"text"或"interactive"（卡片）
            content: 消息内容
            title: 消息标题（用于text类型）
        
        Returns:
            bool: 是否发送成功
        """
        try:
            access_token = self.get_access_token()
            if not access_token:
                return False
            
            # 构建消息内容
            if message_type == "text":
                if title:
                    text_content = f"**{title}**\n\n{content.get('text', '')}" if content else f"**{title}**\n\n"
                else:
                    text_content = content.get('text', '') if content else ""
                
                msg_content = {
                    "text": text_content
                }
            else:
                msg_content = content or {}
            
            url = f"{self.base_url}/im/v1/messages"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            params = {
                "receive_id_type": receive_id_type
            }
            
            payload = {
                "receive_id": receive_id,
                "msg_type": message_type,
                "content": json.dumps(msg_content)
            }
            
            response = requests.post(url, headers=headers, params=params, json=payload, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            logger.debug(f"飞书API响应: code={result.get('code')}, msg={result.get('msg')}, 完整响应: {result}")
            if result.get("code") == 0:
                # 检查响应中是否有message_id（表示真正发送成功）
                message_id = result.get('data', {}).get('message_id', '')
                if message_id:
                    logger.info(f"✅ 飞书消息发送成功: {title or '无标题'}, receive_id={receive_id[:30]}..., message_id={message_id[:30]}...")
                else:
                    logger.warning(f"⚠️ 飞书API返回code=0但无message_id，可能未真正发送: receive_id={receive_id[:30]}..., 响应: {result}")
                return True
            else:
                error_msg = result.get('msg', '未知错误')
                logger.error(f"❌ 飞书消息发送失败: code={result.get('code')}, msg={error_msg}, receive_id={receive_id[:30]}...")
                return False
                
        except Exception as e:
            log_error_with_context(
                logger, e,
                {'function': 'send_message', 'receive_id': receive_id},
                "发送飞书消息失败"
            )
            return False
    
    def send_text_message(
        self,
        chat_id: str,
        message: str,
        title: Optional[str] = None
    ) -> bool:
        """
        发送文本消息到飞书群（便捷方法）
        
        Args:
            chat_id: 群ID
            message: 消息内容
            title: 消息标题
        
        Returns:
            bool: 是否发送成功
        """
        content = {"text": message}
        return self.send_message(
            receive_id=chat_id,
            receive_id_type="chat_id",
            message_type="text",
            content=content,
            title=title
        )
    
    def verify_webhook(self, timestamp: str, nonce: str, encrypted: str, signature: str) -> bool:
        """
        验证webhook请求的签名
        
        Args:
            timestamp: 时间戳
            nonce: 随机字符串
            encrypted: 加密数据
            signature: 签名
        
        Returns:
            bool: 验证是否通过
        """
        try:
            if not self.encrypt_key:
                logger.warning("未配置加密密钥，跳过签名验证")
                return True
            
            # 构建待签名字符串
            string_to_sign = f"{timestamp}{nonce}{self.encrypt_key}{encrypted}"
            
            # 计算签名
            signature_calculated = base64.b64encode(
                hmac.new(
                    self.encrypt_key.encode('utf-8'),
                    string_to_sign.encode('utf-8'),
                    hashlib.sha256
                ).digest()
            ).decode('utf-8')
            
            return signature_calculated == signature
            
        except Exception as e:
            logger.error(f"验证webhook签名失败: {e}")
            return False
    
    def decrypt_message(self, encrypted: str) -> Optional[Dict[str, Any]]:
        """
        解密接收到的消息（如果需要）
        
        Args:
            encrypted: 加密的消息
        
        Returns:
            dict: 解密后的消息，如果解密失败返回None
        """
        # 如果配置了加密，需要实现解密逻辑
        # 这里简化处理，假设消息未加密或已由飞书平台处理
        try:
            # 实际实现需要根据飞书加密算法进行解密
            # 这里返回None表示未实现加密解密
            if self.encrypt_key:
                logger.warning("消息加密解密功能待实现")
            return None
        except Exception as e:
            logger.error(f"解密消息失败: {e}")
            return None
    
    def register_message_handler(self, command: str, handler: Callable):
        """
        注册消息处理器
        
        Args:
            command: 命令关键字（如"查询状态"、"获取信号"等）
            handler: 处理函数，接收(message: Dict) -> str
        """
        self.message_handlers[command] = handler
        logger.info(f"注册消息处理器: {command}")
    
    def handle_message(self, message_data: Dict[str, Any]) -> Optional[str]:
        """
        处理接收到的消息
        
        Args:
            message_data: 消息数据
        
        Returns:
            str: 回复消息，如果无法处理返回None
        """
        try:
            # 提取消息内容
            event = message_data.get('event', {})
            message = event.get('message', {})
            
            # 处理content字段（可能是字符串或字典）
            content_raw = message.get('content', '{}')
            if isinstance(content_raw, str):
                try:
                    content = json.loads(content_raw)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"无法解析消息content（字符串格式）: {content_raw[:100]}")
                    content = {}
            elif isinstance(content_raw, dict):
                content = content_raw
            else:
                logger.warning(f"消息content格式未知: {type(content_raw)}")
                content = {}
            
            text = content.get('text', '').strip()
            
            # 提取发送者信息
            sender = event.get('sender', {})
            sender_id = sender.get('sender_id', {})
            user_id = sender_id.get('user_id', '')
            
            # 如果没有提取到文本，尝试其他方式
            if not text:
                # 尝试直接从message中获取
                text = message.get('text', '').strip()
                if not text:
                    # 尝试从content中直接获取
                    text = str(content_raw).strip() if content_raw else ''
            
            # 清理文本：移除@mention（格式：@_user_xxx 或 @用户 或 @送信息给...）
            import re
            # 移除 @_user_xxx 格式
            text = re.sub(r'@_user_\w+\s*', '', text)
            # 移除 @送信息给... 格式（包含空格的@mention）
            text = re.sub(r'@送信息给[^\n]*?\s+', '', text)
            # 移除 @用户 格式（中文用户名，不包含空格）
            text = re.sub(r'@[^\s]+\s*', '', text)
            text = text.strip()
            
            logger.info(f"收到飞书消息: {text} (原始: {content.get('text', '')[:50]}, 来自: {user_id})")
            
            # 查找匹配的处理器
            for command, handler in self.message_handlers.items():
                if command in text:
                    try:
                        reply = handler(message_data)
                        return reply
                    except Exception as e:
                        logger.error(f"处理消息失败: {e}", exc_info=True)
                        return f"处理命令时出错: {str(e)}"
            
            # 默认回复
            if text:
                reply = self._get_default_reply(text)
                logger.info(f"生成默认回复: {reply[:100]}...")
                return reply
            else:
                logger.warning(f"无法提取消息文本，原始数据: {message_data}")
                return "无法识别消息内容，请输入\"帮助\"查看可用命令"
            
            return None
            
        except Exception as e:
            log_error_with_context(
                logger, e,
                {'function': 'handle_message'},
                "处理飞书消息失败"
            )
            return None
    
    def _get_default_reply(self, text: str) -> str:
        """
        获取默认回复（实现具体命令处理）
        
        Args:
            text: 消息文本
        
        Returns:
            str: 默认回复
        """
        text_lower = text.lower()
        
        if any(keyword in text_lower for keyword in ['帮助', 'help', '命令', '功能']):
            return """📋 可用命令：
• 查询状态 - 查看系统运行状态
• 最新信号 - 获取最新交易信号
• 波动区间 - 查看最新波动区间
• 开盘策略 - 查看今日开盘策略
• 系统信息 - 查看系统详细信息
• 间接指导建议 - 获取间接交易指导建议
• 合约配置 - 查看期权合约配置
• 定时任务 - 查看定时任务状态和下次执行时间
• 波动预测 指数 [代码] - 即时预测指定指数的日内波动区间（如：波动预测 指数 000300）
• 波动预测 ETF [代码] - 即时预测指定ETF的日内波动区间（如：波动预测 ETF 510300）
• 波动预测 期权 [合约代码] - 即时预测指定期权合约的日内波动区间（如：波动预测 期权 10010474）"""
        
        elif any(keyword in text_lower for keyword in ['状态', 'status', '系统状态']):
            return self._handle_status_query()
        
        elif any(keyword in text_lower for keyword in ['信号', 'signal', '最新信号', '交易信号']):
            return self._handle_signal_query()
        
        # 注意：波动预测要放在波动区间之前，避免"波动预测"被"波动区间"匹配
        elif any(keyword in text_lower for keyword in ['波动预测', '预测波动', '区间预测']):
            return self._handle_volatility_prediction(text)
        
        elif any(keyword in text_lower for keyword in ['区间', 'range', '波动', '波动区间']):
            return self._handle_volatility_range_query()
        
        elif any(keyword in text_lower for keyword in ['策略', 'strategy', '开盘策略', '开盘']):
            return self._handle_strategy_query()
        
        elif any(keyword in text_lower for keyword in ['系统信息', '系统', 'info']):
            return self._handle_system_info()
        
        elif any(keyword in text_lower for keyword in ['间接指导', '指导建议', 'guidance', '间接建议']):
            return self._handle_indirect_guidance()
        
        elif any(keyword in text_lower for keyword in ['合约配置', '合约', 'contract', '配置']):
            return self._handle_contract_config()
        
        elif any(keyword in text_lower for keyword in ['定时任务', 'scheduler', '任务状态', '任务列表']):
            return self._handle_scheduler_status()
        
        else:
            return f"收到消息: {text}\n\n输入\"帮助\"查看可用命令"
    
    def _handle_status_query(self) -> str:
        """处理状态查询命令"""
        try:
            from src.system_status import get_current_market_status
            from src.config_loader import load_system_config
            
            config = load_system_config(use_cache=True)
            status = get_current_market_status(config)
            
            status_map = {
                'before_open': '开盘前',
                'trading': '交易中',
                'lunch_break': '午休',
                'after_close': '收盘后',
                'non_trading_day': '非交易日'
            }
            
            market_status = status_map.get(status.get('status', 'unknown'), status.get('status', '未知'))
            is_trading = '是' if status.get('is_trading_time', False) else '否'
            current_time = status.get('current_time', 'N/A')
            
            return f"""📊 系统状态

市场状态: {market_status}
是否交易时间: {is_trading}
当前时间: {current_time}

系统运行正常 ✅"""
            
        except Exception as e:
            logger.error(f"查询系统状态失败: {e}")
            return f"查询系统状态失败: {str(e)}"
    
    def _handle_signal_query(self) -> str:
        """处理信号查询命令"""
        try:
            from src.data_storage import load_signals
            from src.config_loader import load_system_config
            
            config = load_system_config(use_cache=True)
            signals = load_signals(config=config)
            
            if not signals:
                return "📋 最新信号\n\n暂无交易信号"
            
            # 获取最近3条信号
            recent_signals = signals[-3:]
            reply = "📋 最新交易信号\n\n"
            
            for i, signal in enumerate(reversed(recent_signals), 1):
                signal_type = signal.get('signal_type', '未知').upper()
                action = signal.get('action', '未知')
                timestamp = signal.get('timestamp', 'N/A')
                expected_return = signal.get('expected_return_pct', 'N/A')
                risk_reward = signal.get('risk_reward_ratio', 'N/A')
                
                reply += f"{i}. {action}\n"
                reply += f"   时间: {timestamp}\n"
                reply += f"   预期收益: {expected_return}%\n" if isinstance(expected_return, (int, float)) else f"   预期收益: {expected_return}\n"
                reply += f"   风险收益比: {risk_reward}\n" if isinstance(risk_reward, (int, float)) else f"   风险收益比: {risk_reward}\n"
                
                # 添加信号说明
                description = signal.get('description', '')
                if description:
                    reply += f"   信号说明: {description}\n"
                
                # 添加技术指标
                rsi = signal.get('rsi')
                if rsi is not None:
                    reply += f"   RSI: {rsi:.2f}\n"
                
                price_change = signal.get('price_change')
                if price_change is not None:
                    sign = '+' if price_change >= 0 else ''
                    reply += f"   价格变动: {sign}{price_change:.2f}%\n"
                
                # 添加趋势信息
                trend = signal.get('trend', '')
                trend_strength = signal.get('trend_strength')
                if trend:
                    if trend_strength is not None:
                        reply += f"   趋势: {trend} (强度: {trend_strength:.2f})\n"
                    else:
                        reply += f"   趋势: {trend}\n"
                
                # 添加波动区间信息
                volatility_range = signal.get('volatility_range', {})
                if volatility_range:
                    current = volatility_range.get('current')
                    upper = volatility_range.get('upper')
                    lower = volatility_range.get('lower')
                    range_pct = volatility_range.get('range_pct')
                    
                    if current is not None or upper is not None or lower is not None:
                        reply += f"   📊 波动区间: "
                        parts = []
                        if current is not None:
                            parts.append(f"当前: {current:.4f}")
                        if upper is not None:
                            parts.append(f"上轨: {upper:.4f}")
                        if lower is not None:
                            parts.append(f"下轨: {lower:.4f}")
                        if range_pct is not None:
                            parts.append(f"范围: {range_pct:.2f}%")
                        reply += ", ".join(parts) + "\n"
                
                # 添加仓位建议
                position_size = signal.get('position_size')
                if position_size:
                    reply += f"   💰 仓位建议: {position_size}\n"
                
                reply += "\n"
            
            return reply.strip()
            
        except Exception as e:
            logger.error(f"查询信号失败: {e}")
            return f"查询信号失败: {str(e)}"
    
    def _handle_volatility_range_query(self) -> str:
        """处理波动区间查询命令"""
        try:
            from src.data_storage import load_volatility_ranges
            from src.config_loader import load_system_config
            
            config = load_system_config(use_cache=True)
            ranges = load_volatility_ranges(config=config)
            
            if not ranges:
                return "📈 最新波动区间\n\n暂无波动区间数据"
            
            latest = ranges[-1]
            index_range = latest.get('index_range', {})
            
            reply = "📈 最新波动区间\n\n"
            
            if index_range:
                reply += f"指数 (000300):\n"
                reply += f"  当前: {index_range.get('current_price', 'N/A')}\n"
                reply += f"  上轨: {index_range.get('upper', 'N/A')}\n"
                reply += f"  下轨: {index_range.get('lower', 'N/A')}\n"
                reply += f"  方法: {index_range.get('method', 'N/A')}\n\n"
            
            # 支持多标的物格式
            underlyings_data = latest.get('underlyings', {})
            
            if underlyings_data:
                # 新格式：按标的物分组显示
                for underlying, underlying_data in underlyings_data.items():
                    etf_range = underlying_data.get('etf_range', {})
                    call_ranges = underlying_data.get('call_ranges', [])
                    put_ranges = underlying_data.get('put_ranges', [])
                    
                    reply += f"━━━ 标的物: {underlying} ━━━\n\n"
                    
                    if etf_range:
                        reply += f"ETF ({underlying}):\n"
                        reply += f"  当前: {etf_range.get('current_price', 'N/A')}\n"
                        reply += f"  上轨: {etf_range.get('upper', 'N/A')}\n"
                        reply += f"  下轨: {etf_range.get('lower', 'N/A')}\n\n"
                    
                    # 显示该标的物的所有Call合约
                    if call_ranges:
                        reply += f"Call期权（{len(call_ranges)}个合约）:\n"
                        for i, call_range in enumerate(call_ranges):
                            contract_name = call_range.get('name', call_range.get('contract_code', f'Call{i+1}'))
                            reply += f"  【{contract_name}】\n"
                            reply += f"    当前: {call_range.get('current_price', 'N/A')}\n"
                            reply += f"    上轨: {call_range.get('upper', 'N/A')}\n"
                            reply += f"    下轨: {call_range.get('lower', 'N/A')}\n"
                            if call_range.get('strike_price'):
                                reply += f"    行权价: {call_range.get('strike_price')}\n"
                            reply += "\n"
                    
                    # 显示该标的物的所有Put合约
                    if put_ranges:
                        reply += f"Put期权（{len(put_ranges)}个合约）:\n"
                        for i, put_range in enumerate(put_ranges):
                            contract_name = put_range.get('name', put_range.get('contract_code', f'Put{i+1}'))
                            reply += f"  【{contract_name}】\n"
                            reply += f"    当前: {put_range.get('current_price', 'N/A')}\n"
                            reply += f"    上轨: {put_range.get('upper', 'N/A')}\n"
                            reply += f"    下轨: {put_range.get('lower', 'N/A')}\n"
                            if put_range.get('strike_price'):
                                reply += f"    行权价: {put_range.get('strike_price')}\n"
                            reply += "\n"
            else:
                # 向后兼容：单个标的物格式
                etf_range = latest.get('etf_range', {})
                call_ranges = latest.get('call_ranges', [])
                put_ranges = latest.get('put_ranges', [])
                
                
                if etf_range:
                    reply += f"ETF (510300):\n"
                    reply += f"  当前: {etf_range.get('current_price', 'N/A')}\n"
                    reply += f"  上轨: {etf_range.get('upper', 'N/A')}\n"
                    reply += f"  下轨: {etf_range.get('lower', 'N/A')}\n\n"
                
                # 显示所有Call合约
                if call_ranges:
                    reply += f"Call期权（{len(call_ranges)}个合约）:\n"
                    for i, call_range in enumerate(call_ranges):
                        contract_name = call_range.get('name', call_range.get('contract_code', f'Call{i+1}'))
                        reply += f"  【{contract_name}】\n"
                        reply += f"    当前: {call_range.get('current_price', 'N/A')}\n"
                        reply += f"    上轨: {call_range.get('upper', 'N/A')}\n"
                        reply += f"    下轨: {call_range.get('lower', 'N/A')}\n"
                        if call_range.get('strike_price'):
                            reply += f"    行权价: {call_range.get('strike_price')}\n"
                        reply += "\n"
                
                # 显示所有Put合约
                if put_ranges:
                    reply += f"Put期权（{len(put_ranges)}个合约）:\n"
                    for i, put_range in enumerate(put_ranges):
                        contract_name = put_range.get('name', put_range.get('contract_code', f'Put{i+1}'))
                        reply += f"  【{contract_name}】\n"
                        reply += f"    当前: {put_range.get('current_price', 'N/A')}\n"
                        reply += f"    上轨: {put_range.get('upper', 'N/A')}\n"
                        reply += f"    下轨: {put_range.get('lower', 'N/A')}\n"
                        if put_range.get('strike_price'):
                            reply += f"    行权价: {put_range.get('strike_price')}\n"
                        reply += "\n"
            
            reply += f"\n更新时间: {latest.get('timestamp', 'N/A')}"
            
            return reply
            
        except Exception as e:
            logger.error(f"查询波动区间失败: {e}")
            return f"查询波动区间失败: {str(e)}"
    
    def _handle_strategy_query(self) -> str:
        """处理开盘策略查询命令"""
        try:
            from src.data_storage import load_trend_analysis
            from src.config_loader import load_system_config
            
            config = load_system_config(use_cache=True)
            strategy = load_trend_analysis(analysis_type='before_open', config=config)
            
            if not strategy:
                return "📊 开盘策略\n\n暂无开盘策略数据"
            
            final_trend = strategy.get('final_trend', '未知')
            final_strength = strategy.get('final_strength', 0)
            opening_strategy = strategy.get('opening_strategy', {})
            direction = opening_strategy.get('direction', '未知')
            position_size = opening_strategy.get('position_size', '未知')
            
            reply = f"""📊 开盘策略

整体趋势: {final_trend}
趋势强度: {final_strength:.2f}
操作方向: {direction}
仓位建议: {position_size}

信号阈值: {opening_strategy.get('signal_threshold', '正常')}
Call建议: {'✅' if opening_strategy.get('suggest_call', False) else '❌'}
Put建议: {'✅' if opening_strategy.get('suggest_put', False) else '❌'}"""
            
            return reply
            
        except Exception as e:
            logger.error(f"查询开盘策略失败: {e}")
            return f"查询开盘策略失败: {str(e)}"
    
    def _handle_system_info(self) -> str:
        """处理系统信息查询命令"""
        try:
            from src.system_status import get_current_market_status
            from src.config_loader import load_system_config
            from src.data_storage import load_volatility_ranges, load_signals, load_trend_analysis
            
            config = load_system_config(use_cache=True)
            status = get_current_market_status(config)
            
            # 统计今日数据
            ranges = load_volatility_ranges(config=config)
            signals = load_signals(config=config)
            strategy = load_trend_analysis(analysis_type='before_open', config=config)
            
            reply = f"""💻 系统信息

系统状态: ✅ 运行正常
市场状态: {status.get('status', '未知')}
当前时间: {status.get('current_time', 'N/A')}

今日数据统计:
• 波动区间记录: {len(ranges)} 条
• 交易信号: {len(signals)} 条
• 开盘策略: {'已生成' if strategy else '未生成'}

系统版本: 期权交易助手 v1.0"""
            
            return reply
            
        except Exception as e:
            logger.error(f"查询系统信息失败: {e}")
            return f"查询系统信息失败: {str(e)}"
    
    def _handle_scheduler_status(self) -> str:
        """处理定时任务状态查询命令"""
        try:
            import pytz
            from datetime import datetime
            from src.system_status import is_trading_day, get_current_market_status
            from src.config_loader import load_system_config
            
            config = load_system_config(use_cache=True)
            tz_shanghai = pytz.timezone('Asia/Shanghai')
            now = datetime.now(tz_shanghai)
            
            # 获取市场状态
            market_status = get_current_market_status(config)
            is_trading = is_trading_day(now, config)
            
            # 获取scheduler实例（从全局注册表）
            try:
                from src.scheduler_registry import get_scheduler, is_scheduler_available
                
                scheduler = get_scheduler()
                
                if scheduler is None:
                    return "⏰ 定时任务状态\n\n❌ 定时任务调度器未初始化（scheduler为None）"
                
                # 检查scheduler是否正在运行
                if not hasattr(scheduler, 'running') or not scheduler.running:
                    return "⏰ 定时任务状态\n\n⚠️ 定时任务调度器已创建但未启动"
                
                jobs = scheduler.get_jobs()
                
                reply = f"""⏰ 定时任务状态

系统时间: {now.strftime('%Y-%m-%d %H:%M:%S %A')}
时区: Asia/Shanghai
是否交易日: {'是' if is_trading else '否'}
市场状态: {market_status.get('status', '未知')}
调度器状态: {'运行中' if scheduler.running else '已停止'}

已注册任务 ({len(jobs)} 个):
"""
                
                for job in jobs:
                    next_run = job.next_run_time
                    if next_run:
                        next_run_str = next_run.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        next_run_str = "未安排"
                    
                    reply += f"\n• {job.name} (ID: {job.id})\n"
                    reply += f"  下次执行: {next_run_str}\n"
                    reply += f"  触发器: {job.trigger}\n"
                
                return reply
                
            except AttributeError as e:
                logger.error(f"无法访问定时任务调度器: {e}", exc_info=True)
                return f"⏰ 定时任务状态\n\n⚠️ 无法访问定时任务调度器（AttributeError: {str(e)}）"
            except Exception as e:
                logger.error(f"查询定时任务状态失败: {e}", exc_info=True)
                return f"⏰ 定时任务状态\n\n❌ 查询失败: {str(e)}"
            
        except Exception as e:
            logger.error(f"查询定时任务状态失败: {e}", exc_info=True)
            return f"查询定时任务状态失败: {str(e)}"
    
    def _handle_indirect_guidance(self) -> str:
        """处理间接指导建议查询命令"""
        try:
            from src.indirect_guidance import generate_indirect_guidance
            from src.data_storage import load_volatility_ranges
            from src.data_collector import (
                get_etf_current_price, get_option_current_price, fetch_option_greeks_sina
            )
            from src.config_loader import load_system_config, get_contract_code, get_contract_codes
            from src.trend_analyzer import analyze_index_trend
            from src.data_collector import fetch_index_daily_em
            from datetime import datetime, timedelta
            import pytz
            
            config = load_system_config(use_cache=True)
            
            # 1. 获取最新波动区间
            ranges = load_volatility_ranges(config=config)
            if not ranges:
                return "💡 间接指导建议\n\n暂无波动区间数据，无法生成指导建议"
            
            latest_range = ranges[-1]
            
            # 2. 获取指数趋势（从日线数据计算）
            today = datetime.now(pytz.timezone('Asia/Shanghai')).strftime("%Y%m%d")
            start_date = (datetime.now(pytz.timezone('Asia/Shanghai')) - timedelta(days=90)).strftime("%Y%m%d")
            
            hs300_daily = fetch_index_daily_em(
                symbol="000300",
                period="daily",
                start_date=start_date,
                end_date=today
            )
            
            if hs300_daily is None or hs300_daily.empty:
                return "💡 间接指导建议\n\n无法获取指数数据，无法生成指导建议"
            
            index_trend, trend_strength = analyze_index_trend(hs300_daily, "000300")
            index_trend_dict = {
                'direction': index_trend,
                'strength': trend_strength
            }
            
            # 3. 获取波动区间数据
            index_range_data = latest_range.get('index_range', {})
            etf_range_data = latest_range.get('etf_range', {})
            
            if not index_range_data:
                return "💡 间接指导建议\n\n无法获取波动区间数据，无法生成指导建议"
            
            index_range_dict = {
                'upper': index_range_data.get('upper'),
                'lower': index_range_data.get('lower')
            }
            
            # 4. 获取ETF当前价格和ETF波动区间
            etf_price = get_etf_current_price()
            if etf_price is None:
                # 优先使用ETF区间中的当前价格
                etf_price = etf_range_data.get('current_price') or index_range_data.get('current_price', 0)
            
            # 如果有ETF波动区间，使用ETF区间；否则使用指数区间（但需要转换单位）
            etf_range_dict = None
            if etf_range_data and etf_range_data.get('upper') and etf_range_data.get('lower'):
                etf_range_dict = {
                    'upper': etf_range_data.get('upper'),
                    'lower': etf_range_data.get('lower')
                }
            
            # 5. 获取期权价格和Greeks（支持多个合约，使用第一个合约用于查询）
            option_contracts = config.get('option_contracts', {}) if config else {}
            
            # 获取所有合约配置（支持多个合约）
            call_contracts_config = get_contract_codes(option_contracts, 'call', verify_strike=False)
            put_contracts_config = get_contract_codes(option_contracts, 'put', verify_strike=False)
            
            # 向后兼容：如果没有配置多个合约，使用旧的单个合约
            if not call_contracts_config:
                call_contract_code = get_contract_code(option_contracts, 'call')
                if call_contract_code:
                    call_contracts_config = [{'contract_code': call_contract_code}]
            
            if not put_contracts_config:
                put_contract_code = get_contract_code(option_contracts, 'put')
                if put_contract_code:
                    put_contracts_config = [{'contract_code': put_contract_code}]
            
            # 使用第一个合约进行查询（用于显示）
            call_price = None
            put_price = None
            call_greeks = None
            put_greeks = None
            call_iv = None
            put_iv = None
            
            if call_contracts_config:
                call_contract_code = call_contracts_config[0].get('contract_code')
                if call_contract_code:
                    try:
                        call_price = get_option_current_price(call_contract_code)
                        call_greeks = fetch_option_greeks_sina(call_contract_code)
                        if call_greeks:
                            call_iv = call_greeks.get('iv', None)
                    except Exception as e:
                        logger.debug(f"获取Call期权数据失败: {e}")
            
            if put_contracts_config:
                put_contract_code = put_contracts_config[0].get('contract_code')
                if put_contract_code:
                    try:
                        put_price = get_option_current_price(put_contract_code)
                        put_greeks = fetch_option_greeks_sina(put_contract_code)
                        if put_greeks:
                            put_iv = put_greeks.get('iv', None)
                    except Exception as e:
                        logger.debug(f"获取Put期权数据失败: {e}")
            
            # 6. 获取指数当前价格（用于计算指数在指数区间中的位置）
            index_current_price = index_range_data.get('current_price')
            if not index_current_price and hs300_daily is not None and not hs300_daily.empty:
                # 从日线数据中获取最新收盘价
                if '收盘' in hs300_daily.columns:
                    index_current_price = float(hs300_daily['收盘'].iloc[-1])
            
            # 7. 生成间接指导建议
            guidance = generate_indirect_guidance(
                index_trend=index_trend_dict,
                index_range=index_range_dict,
                etf_current_price=etf_price,
                call_option_price=call_price,
                put_option_price=put_price,
                call_iv=call_iv,
                put_iv=put_iv,
                call_greeks=call_greeks,
                put_greeks=put_greeks,
                etf_range=etf_range_dict,
                index_current_price=index_current_price
            )
            
            if 'error' in guidance:
                return f"💡 间接指导建议\n\n生成失败: {guidance.get('error', '未知错误')}"
            
            # 7. 格式化输出
            reply = "💡 间接指导建议\n\n"
            reply += f"📊 市场概况\n"
            reply += f"指数趋势: {guidance.get('index_trend', '未知')} (强度: {guidance.get('trend_strength', 0):.2f})\n"
            
            index_range_info = guidance.get('index_range', {})
            reply += f"波动区间: [{index_range_info.get('lower', 'N/A')}, {index_range_info.get('upper', 'N/A')}]\n"
            reply += f"当前价格: {index_range_info.get('current', 'N/A')}\n"
            reply += f"区间位置: {index_range_info.get('position', 0.5):.1%}\n\n"
            
            reply += f"💭 建议摘要\n"
            reply += f"{guidance.get('summary', '暂无建议')}\n\n"
            
            # 显示详细建议
            suggestions = guidance.get('suggestions', [])
            if suggestions:
                reply += f"📝 详细建议\n"
                for i, suggestion in enumerate(suggestions[:5], 1):  # 最多显示5条
                    suggestion_type = suggestion.get('type', 'unknown')
                    message = suggestion.get('message', '')
                    action = suggestion.get('action', '')
                    
                    if message:
                        reply += f"{i}. {message}\n"
                    elif action:
                        reply += f"{i}. {action}\n"
                    reply += "\n"
            
            reply += f"⚠️ 风险提示: {guidance.get('risk_warning', '设置5%止损，仅参考，不构成投资建议')}\n"
            reply += f"\n更新时间: {guidance.get('timestamp', 'N/A')}"
            
            return reply
            
        except Exception as e:
            logger.error(f"查询间接指导建议失败: {e}", exc_info=True)
            return f"查询间接指导建议失败: {str(e)}"
    
    def _handle_contract_config(self) -> str:
        """处理合约配置查询命令"""
        try:
            from src.config_loader import load_contract_config, get_contract_code
            from src.data_collector import get_etf_current_price
            
            # 加载合约配置
            contract_config = load_contract_config(use_cache=True)
            
            if not contract_config:
                return "📋 合约配置\n\n暂无合约配置信息"
            
            reply = "📋 期权合约配置\n\n"
            
            # 基础信息
            current_month = contract_config.get('current_month', '未配置')
            underlying = contract_config.get('underlying', '510300')
            reply += f"📊 基础信息\n"
            reply += f"交易月份: {current_month}\n"
            reply += f"标的物: {underlying}\n"
            
            # 获取ETF当前价格（用于显示相对位置）
            try:
                etf_price = get_etf_current_price()
                if etf_price:
                    reply += f"ETF当前价格: {etf_price:.3f}\n"
            except:
                pass
            
            reply += "\n"
            
            # Call期权配置（支持多个合约）
            from src.config_loader import get_contract_codes
            call_contracts_config = get_contract_codes(contract_config, 'call', verify_strike=False)
            put_contracts_config = get_contract_codes(contract_config, 'put', verify_strike=False)
            
            # 向后兼容：如果没有配置多个合约，使用旧的单个合约
            if not call_contracts_config:
                call_config = contract_config.get('call_contract', {})
                call_contract_code = get_contract_code(contract_config, 'call', verify_strike=False)
                if call_contract_code:
                    call_contracts_config = [{
                        'contract_code': call_contract_code,
                        'strike_price': call_config.get('strike_price'),
                        'expiry_date': call_config.get('expiry_date'),
                        'name': call_contract_code
                    }]
            
            if not put_contracts_config:
                put_config = contract_config.get('put_contract', {})
                put_contract_code = get_contract_code(contract_config, 'put', verify_strike=False)
                if put_contract_code:
                    put_contracts_config = [{
                        'contract_code': put_contract_code,
                        'strike_price': put_config.get('strike_price'),
                        'expiry_date': put_config.get('expiry_date'),
                        'name': put_contract_code
                    }]
            
            # 显示所有Call合约
            reply += f"📈 Call期权（看涨，共{len(call_contracts_config)}个）\n"
            for i, call_contract in enumerate(call_contracts_config, 1):
                call_contract_code = call_contract.get('contract_code')
                call_strike = call_contract.get('strike_price')
                call_expiry = call_contract.get('expiry_date')
                call_name = call_contract.get('name', call_contract_code or f'Call{i}')
                
                if len(call_contracts_config) > 1:
                    reply += f"\n【{call_name}】\n"
                else:
                    reply += f"\n"
                
                if call_contract_code:
                    reply += f"合约代码: {call_contract_code}\n"
                else:
                    reply += f"合约代码: 未配置\n"
                
                if call_strike:
                    reply += f"行权价: {call_strike}\n"
                    if etf_price:
                        moneyness = "实值" if etf_price > call_strike else ("平值" if abs(etf_price - call_strike) < 0.01 else "虚值")
                        reply += f"虚实状态: {moneyness}\n"
                else:
                    reply += f"行权价: 未配置\n"
                
                if call_expiry:
                    reply += f"到期日: {call_expiry}\n"
                else:
                    reply += f"到期日: 未配置\n"
            
            reply += "\n"
            
            # 显示所有Put合约
            reply += f"📉 Put期权（看跌，共{len(put_contracts_config)}个）\n"
            for i, put_contract in enumerate(put_contracts_config, 1):
                put_contract_code = put_contract.get('contract_code')
                put_strike = put_contract.get('strike_price')
                put_expiry = put_contract.get('expiry_date')
                put_name = put_contract.get('name', put_contract_code or f'Put{i}')
                
                if len(put_contracts_config) > 1:
                    reply += f"\n【{put_name}】\n"
                else:
                    reply += f"\n"
                
                if put_contract_code:
                    reply += f"合约代码: {put_contract_code}\n"
                else:
                    reply += f"合约代码: 未配置\n"
                
                if put_strike:
                    reply += f"行权价: {put_strike}\n"
                    if etf_price:
                        moneyness = "实值" if etf_price < put_strike else ("平值" if abs(etf_price - put_strike) < 0.01 else "虚值")
                        reply += f"虚实状态: {moneyness}\n"
                else:
                    reply += f"行权价: 未配置\n"
                
                if put_expiry:
                    reply += f"到期日: {put_expiry}\n"
                else:
                    reply += f"到期日: 未配置\n"
            
            reply += "\n"
            reply += "💡 提示: 可通过配置文件或WEB界面修改合约配置"
            
            return reply
            
        except Exception as e:
            logger.error(f"查询合约配置失败: {e}", exc_info=True)
            return f"查询合约配置失败: {str(e)}"
    
    def _handle_volatility_prediction(self, text: str) -> str:
        """处理波动预测命令"""
        try:
            import re
            from src.on_demand_predictor import (
                predict_index_volatility_range_on_demand,
                predict_etf_volatility_range_on_demand,
                predict_option_volatility_range_on_demand
            )
            
            # 解析命令格式：波动预测 [类型] [代码]
            # 支持格式：波动预测 指数 000300、波动预测指数000300、波动预测 ETF 510300 等
            text_clean = text.strip()
            
            # 提取类型和代码
            # 支持格式：波动预测 指数 000300、波动预测指数000300、波动预测 ETF 510300 等
            pattern = r'波动预测\s*(指数|ETF|etf|期权)\s*(\d+)'
            match = re.search(pattern, text_clean, re.IGNORECASE)
            
            # 如果第一次匹配失败，尝试连续格式（无空格）
            if not match:
                pattern2 = r'波动预测(指数|ETF|etf|期权)(\d+)'
                match = re.search(pattern2, text_clean, re.IGNORECASE)
            
            # 如果还是失败，尝试更宽松的匹配（允许前后有其他文本）
            if not match:
                pattern3 = r'(?:波动预测|预测波动|区间预测)\s*(?:指数|ETF|etf|期权)?\s*(?:ETF|etf|指数|期权)?\s*(\d{6})'
                match3 = re.search(pattern3, text_clean, re.IGNORECASE)
                if match3:
                    code = match3.group(1)
                    # 尝试从文本中推断类型
                    if 'etf' in text_clean.lower() or '510' in code:
                        pred_type_raw = 'ETF'
                        match = type('Match', (), {'group': lambda self, n: 'ETF' if n == 1 else code})()
                    elif '指数' in text_clean or '000' in code:
                        pred_type_raw = '指数'
                        match = type('Match', (), {'group': lambda self, n: '指数' if n == 1 else code})()
                    elif '期权' in text_clean or len(code) == 8:
                        pred_type_raw = '期权'
                        match = type('Match', (), {'group': lambda self, n: '期权' if n == 1 else code})()
            
            if not match:
                return """❌ 命令格式错误

正确格式：
• 波动预测 指数 000300
• 波动预测 ETF 510300
• 波动预测 期权 10010474

示例：
• 波动预测 指数 000300
• 波动预测 ETF 510300
• 波动预测 期权 10010474"""
            
            pred_type_raw = match.group(1)
            code = match.group(2)
            
            # 标准化类型（处理大小写和中文）
            pred_type = pred_type_raw.lower()
            if '指数' in pred_type_raw or pred_type == 'index':
                pred_type_normalized = 'index'
            elif pred_type == 'etf':
                pred_type_normalized = 'etf'
            elif '期权' in pred_type_raw or pred_type == 'option':
                pred_type_normalized = 'option'
            else:
                return f"❌ 不支持的类型: {pred_type_raw}\n\n支持的类型：指数、ETF、期权"
            
            # 智能识别：如果用户说"指数"但代码是ETF代码（51开头或159开头），自动转换为ETF
            if pred_type_normalized == 'index' and (code.startswith('51') or code.startswith('159')):
                logger.info(f"检测到ETF代码 {code}，但用户指定了'指数'类型，自动转换为ETF预测")
                pred_type_normalized = 'etf'
            
            # 根据类型调用对应的预测函数
            if pred_type_normalized == 'index':
                result = predict_index_volatility_range_on_demand(symbol=code, config=self.config)
            elif pred_type_normalized == 'etf':
                result = predict_etf_volatility_range_on_demand(symbol=code, config=self.config)
            elif pred_type_normalized == 'option':
                result = predict_option_volatility_range_on_demand(contract_code=code, config=self.config)
            else:
                return f"❌ 不支持的类型: {pred_type_raw}\n\n支持的类型：指数、ETF、期权"
            
            # 检查结果
            if not result.get('success', False):
                error_msg = result.get('error', '未知错误')
                return f"❌ 预测失败\n\n错误信息: {error_msg}"
            
            # 格式化返回结果
            pred_type_name = {
                'index': '指数',
                'etf': 'ETF',
                'option': '期权'
            }.get(result.get('type', ''), '')
            
            reply = f"📊 {pred_type_name}波动区间预测\n\n"
            
            # 基本信息
            if result.get('type') == 'index':
                reply += f"指数代码: {result.get('symbol', 'N/A')} ({result.get('symbol_name', 'N/A')})\n"
            elif result.get('type') == 'etf':
                reply += f"ETF代码: {result.get('symbol', 'N/A')} ({result.get('symbol_name', 'N/A')})\n"
            elif result.get('type') == 'option':
                reply += f"合约代码: {result.get('contract_code', 'N/A')}\n"
                if result.get('underlying'):
                    reply += f"标的物: {result.get('underlying')}\n"
            
            reply += f"当前价格: {result.get('current_price', 'N/A')}\n"
            reply += f"预测上轨: {result.get('upper', 'N/A'):.4f}\n" if isinstance(result.get('upper'), (int, float)) else f"预测上轨: {result.get('upper', 'N/A')}\n"
            reply += f"预测下轨: {result.get('lower', 'N/A'):.4f}\n" if isinstance(result.get('lower'), (int, float)) else f"预测下轨: {result.get('lower', 'N/A')}\n"
            reply += f"波动范围: {result.get('range_pct', 'N/A'):.2f}%\n" if isinstance(result.get('range_pct'), (int, float)) else f"波动范围: {result.get('range_pct', 'N/A')}\n"
            reply += f"置信度: {result.get('confidence', 'N/A')}\n" if isinstance(result.get('confidence'), (int, float)) else f"置信度: {result.get('confidence', 'N/A')}\n"
            reply += f"计算方法: {result.get('method', 'N/A')}\n"
            reply += f"剩余交易时间: {result.get('remaining_minutes', 'N/A')}分钟\n\n"
            
            # 当前位置分析
            reply += "📍 当前位置分析\n"
            position = result.get('position', 0.5)
            position_desc = result.get('position_desc', '区间中部')
            trend_direction = result.get('trend_direction', '震荡整理')
            
            reply += f"区间位置: {position * 100:.1f}% ({position_desc})\n"
            reply += f"趋势判断: {trend_direction}\n"
            
            # 技术指标
            rsi_value = result.get('rsi_value')
            rsi_status = result.get('rsi_status')
            if rsi_value is not None:
                rsi_status_text = f" ({rsi_status})" if rsi_status else ""
                reply += f"技术指标: RSI={rsi_value:.2f}{rsi_status_text}\n"
            else:
                reply += "技术指标: RSI=N/A\n"
            
            # 期权特有信息
            if result.get('type') == 'option':
                delta = result.get('delta')
                iv = result.get('iv')
                if delta is not None:
                    reply += f"Delta: {delta:.4f}\n" if isinstance(delta, (int, float)) else f"Delta: {delta}\n"
                if iv is not None:
                    reply += f"IV: {iv:.2f}%\n" if isinstance(iv, (int, float)) else f"IV: {iv}\n"
            
            reply += f"\n💡 说明：{result.get('method', '综合方法计算')}\n"
            reply += f"更新时间: {result.get('timestamp', 'N/A')}"
            
            # ========== LLM增强：追加大模型洞见 ==========
            llm_summary = result.get('llm_summary')
            if llm_summary:
                reply += f"\n\n**大模型洞见（LLM）**：\n{llm_summary}"
            # ========== LLM增强结束 ==========
            
            return reply
            
        except Exception as e:
            logger.error(f"处理波动预测命令失败: {e}", exc_info=True)
            return f"❌ 处理波动预测命令失败: {str(e)}"


def create_feishu_app_bot(config: Optional[Dict] = None) -> Optional[FeishuAppBot]:
    """
    创建飞书应用机器人实例（便捷函数）
    
    Args:
        config: 系统配置
    
    Returns:
        FeishuAppBot: 机器人实例，如果配置不完整返回None
    """
    try:
        bot = FeishuAppBot(config)
        if bot.app_id and bot.app_secret:
            return bot
        else:
            logger.warning("飞书应用凭证未配置，无法创建应用机器人")
            return None
    except Exception as e:
        logger.error(f"创建飞书应用机器人失败: {e}")
        return None
