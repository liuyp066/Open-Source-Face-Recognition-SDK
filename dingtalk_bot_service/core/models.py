"""
钉钉消息实体与数据结构定义
完全解耦，无第三方重度依赖，便于移植
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime


@dataclass
class InboundMessage:
    """接收到的钉钉消息对象"""
    msg_id: str
    msg_type: str                                    # text, picture, audio, file, etc.
    conversation_type: str                           # "1" = 单聊/私聊, "2" = 群聊
    conversation_id: str                             # 会话 ID
    conversation_title: Optional[str] = None         # 群名称（如果是群聊）
    sender_id: str = ""                              # 发送人 ID
    sender_staff_id: Optional[str] = None            # 发送人企业工号 / StaffId
    sender_nick: str = ""                            # 发送人昵称
    content: str = ""                                # 消息文本内容
    session_webhook: Optional[str] = None            # 当前消息专用的即时回复 Webhook (最核心)
    is_at_all: bool = False                          # 是否 @所有人
    is_in_at_list: bool = False                      # 是否 @了机器人
    created_at: datetime = field(default_factory=datetime.now)
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_direct_chat(self) -> bool:
        """是否为单聊/私聊"""
        return self.conversation_type == "1"

    @property
    def is_group_chat(self) -> bool:
        """是否为群聊"""
        return self.conversation_type == "2"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InboundMessage":
        """从钉钉原始回调 JSON 解析构建"""
        msg_type = data.get("msgtype", "text")
        
        # 提取文本内容
        content = ""
        if msg_type == "text":
            content = (data.get("text") or {}).get("content", "").strip()
        elif "content" in data and isinstance(data["content"], dict):
            content = data["content"].get("recognition", "") or str(data.get("content", ""))
        elif "content" in data:
            content = str(data.get("content", ""))

        # 提取会话标题
        conv_title = data.get("conversationTitle")
        
        # 提取 @ 状态
        is_in_at_list = data.get("isInAtList", False)
        is_at_all = (data.get("atUsers") or [{}])[0].get("dingtalkId") == "all" if data.get("atUsers") else False

        return cls(
            msg_id=data.get("msgId", ""),
            msg_type=msg_type,
            conversation_type=str(data.get("conversationType", "1")),
            conversation_id=data.get("conversationId", ""),
            conversation_title=conv_title,
            sender_id=data.get("senderId", ""),
            sender_staff_id=data.get("senderStaffId"),
            sender_nick=data.get("senderNick", "未知用户"),
            content=content,
            session_webhook=data.get("sessionWebhook"),
            is_at_all=is_at_all,
            is_in_at_list=is_in_at_list,
            raw_data=data
        )


@dataclass
class SendResult:
    """消息发送结果"""
    success: bool
    message_id: Optional[str] = None
    error_message: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None
