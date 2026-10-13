"""
钉钉核心 SDK 导出模块
可无缝复制到现有微信机器人项目中直接使用
"""
from .models import InboundMessage, SendResult
from .openapi import DingTalkOpenAPI
from .bot import DingTalkBot

__all__ = ["DingTalkBot", "InboundMessage", "SendResult", "DingTalkOpenAPI"]
