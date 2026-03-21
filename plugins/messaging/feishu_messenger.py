"""
兼容层：FeishuMessenger 类
将旧的 FeishuMessenger 类接口重定向到新的 tool_send_feishu_message 函数
"""

from typing import Optional, Dict, Any
import sys
import os

# 添加父目录到路径
_parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

try:
    from plugins.notification.send_feishu_message import send_feishu_message, tool_send_feishu_message
except ImportError:
    # 如果导入失败，提供空实现
    def send_feishu_message(*args, **kwargs):
        return {"success": False, "error": "FeishuMessenger not available"}
    
    def tool_send_feishu_message(*args, **kwargs):
        return {"success": False, "error": "FeishuMessenger not available"}


class FeishuMessenger:
    """
    兼容类：将旧的 FeishuMessenger 类接口重定向到新的函数接口
    """
    
    def __init__(
        self,
        webhook_url: Optional[str] = None,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None
    ):
        """
        初始化 FeishuMessenger
        
        Args:
            webhook_url: 飞书 Webhook URL
            app_id: 飞书应用 ID
            app_secret: 飞书应用密钥
        """
        self.webhook_url = webhook_url
        self.app_id = app_id
        self.app_secret = app_secret
    
    def send_message(
        self,
        message: str,
        message_type: str = "text",
        receiver_id: Optional[str] = None,
        receiver_type: str = "chat"
    ) -> Dict[str, Any]:
        """
        发送消息
        
        Args:
            message: 消息内容
            message_type: 消息类型 "text"/"rich_text"/"card"
            receiver_id: 接收者ID（使用API时必填）
            receiver_type: 接收者类型 "user"/"chat"
        
        Returns:
            Dict: 发送结果
        """
        return send_feishu_message(
            message_type=message_type,
            content=message,
            receiver_id=receiver_id,
            receiver_type=receiver_type,
            webhook_url=self.webhook_url,
            app_id=self.app_id,
            app_secret=self.app_secret
        )
    
    def send_text(self, message: str, **kwargs) -> Dict[str, Any]:
        """发送文本消息"""
        return self.send_message(message, message_type="text", **kwargs)
    
    def send_rich_text(self, message: str, **kwargs) -> Dict[str, Any]:
        """发送富文本消息"""
        return self.send_message(message, message_type="rich_text", **kwargs)
    
    def send_card(self, message: str, **kwargs) -> Dict[str, Any]:
        """发送卡片消息"""
        return self.send_message(message, message_type="card", **kwargs)


# 为了向后兼容，也导出函数接口
__all__ = ['FeishuMessenger', 'send_feishu_message', 'tool_send_feishu_message']
