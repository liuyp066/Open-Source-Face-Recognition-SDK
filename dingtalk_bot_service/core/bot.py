"""
钉钉机器人核心客户端 (DingTalkBot)
封装 Stream 长连接监听、去重、回调分发、被动即时回复与主动推送接口
完全独立，可直接移植到任意 Python 项目（包括微信机器人项目）
"""
import asyncio
import json
import logging
import threading
import time
from typing import Callable, List, Optional, Any, Dict
from urllib.parse import quote_plus

import requests
import websockets
from dingtalk_stream import (
    DingTalkStreamClient,
    Credential,
    ChatbotHandler,
    CallbackMessage,
    AckMessage,
    ChatbotMessage,
)

from .models import InboundMessage, SendResult
from .openapi import DingTalkOpenAPI

logger = logging.getLogger("DingTalkBot")


class _GracefulStreamClient(DingTalkStreamClient):
    """支持平滑停止的 Stream 客户端子类"""

    def __init__(self, credential):
        super().__init__(credential)
        self.stopped = False

    async def start(self):
        self.pre_start()
        while not self.stopped:
            try:
                connection = self.open_connection()
                if not connection:
                    self.logger.error("Open connection 失败，将在 5 秒后重试...")
                    for _ in range(5):
                        if self.stopped:
                            break
                        await asyncio.sleep(1)
                    continue

                uri = f"{connection['endpoint']}?ticket={quote_plus(connection['ticket'])}"
                async with websockets.connect(uri) as websocket:
                    self.websocket = websocket
                    self.logger.info("已成功建立钉钉 WebSocket 长连接！")
                    keepalive_task = asyncio.create_task(self.keepalive(websocket))
                    
                    async for raw_message in websocket:
                        if self.stopped:
                            break
                        json_message = json.loads(raw_message)
                        asyncio.create_task(self.background_task(json_message))
                        
                    keepalive_task.cancel()
            except (asyncio.exceptions.CancelledError, websockets.exceptions.ConnectionClosedError) as e:
                if self.stopped:
                    break
                self.logger.warning(f"网络连接关闭: {e}，正在重连...")
                await asyncio.sleep(2)
            except Exception as e:
                if self.stopped:
                    break
                self.logger.exception(f"Stream 连接异常: {e}，将在 3 秒后重试...")
                await asyncio.sleep(3)

    async def close(self):
        self.stopped = True
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception:
                pass


class DingTalkBot:
    """
    钉钉机器人核心类
    
    使用示例:
        bot = DingTalkBot(client_id="xxx", client_secret="yyy")
        
        @bot.on_message
        def handle_msg(msg: InboundMessage):
            print(f"收到消息: {msg.content}")
            bot.reply_text(msg, f"复读: {msg.content}")
            
        bot.start_in_background() # 后台长连接运行
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        auto_reply: bool = False,
        auto_reply_template: str = "收到消息：{content}",
    ):
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.auto_reply = auto_reply
        self.auto_reply_template = auto_reply_template

        # 开放平台 API 客户端
        self.openapi = DingTalkOpenAPI(client_id, client_secret)

        # 消息处理器回调列表
        self._message_handlers: List[Callable[[InboundMessage], Any]] = []

        # 运行状态统计
        self.status = "disconnected"  # disconnected / connecting / connected / error
        self.connected_at: Optional[float] = None
        self.last_inbound_at: Optional[float] = None
        self.received_count = 0
        self.sent_count = 0
        self.last_error: Optional[str] = None

        # 消息去重缓存 (msg_id -> timestamp)，保留最近 5 分钟
        self._processed_msg_ids: Dict[str, float] = {}

        # 线程与客户端句柄
        self._stream_client: Optional[_GracefulStreamClient] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def on_message(self, handler: Callable[[InboundMessage], Any]):
        """注册消息回调函数（支持同步与异步函数）"""
        self._message_handlers.append(handler)
        return handler

    def _is_duplicate_message(self, msg_id: str) -> bool:
        """检查并标记重复消息（防止钉钉超时重发导致的重复处理）"""
        if not msg_id:
            return False
        now = time.time()
        # 清理 5 分钟以前的过期记账
        expired_keys = [k for k, v in self._processed_msg_ids.items() if now - v > 300]
        for k in expired_keys:
            self._processed_msg_ids.pop(k, None)

        if msg_id in self._processed_msg_ids:
            return True
        self._processed_msg_ids[msg_id] = now
        return False

    def _dispatch_inbound(self, msg: InboundMessage):
        """分发接收到的消息"""
        self.last_inbound_at = time.time()
        self.received_count += 1
        logger.info(f"收到消息: [{msg.sender_nick}] ({'私聊' if msg.is_direct_chat else '群聊'}): {msg.content}")

        # 1. 触发用户注册的回调钩子
        for handler in self._message_handlers:
            try:
                res = handler(msg)
                if asyncio.iscoroutine(res):
                    # 如果回调是协程，调度执行
                    if self._loop and self._loop.is_running():
                        asyncio.run_coroutine_threadsafe(res, self._loop)
            except Exception as e:
                logger.exception(f"消息处理器执行出错: {e}")

        # 2. 如果开启了自动回显回复且有 sessionWebhook
        if self.auto_reply and msg.session_webhook:
            reply_text = self.auto_reply_template.format(
                content=msg.content,
                sender=msg.sender_nick,
                msg_id=msg.msg_id
            )
            self.reply_text(msg, reply_text)

    # ============ 消息发送与被动回复接口 ============

    def reply_text(self, msg: InboundMessage, content: str) -> SendResult:
        """
        通过当前消息的 session_webhook 快速原地回复文本消息
        """
        if not msg.session_webhook:
            return SendResult(success=False, error_message="当前消息无 session_webhook，无法原地回复")

        headers = {"Content-Type": "application/json"}
        payload = {
            "msgtype": "text",
            "text": {"content": content},
            "at": {"atUserIds": [msg.sender_staff_id] if msg.sender_staff_id else []}
        }
        try:
            resp = requests.post(msg.session_webhook, headers=headers, json=payload, timeout=8)
            data = resp.json() if resp.status_code == 200 else {}
            self.sent_count += 1
            return SendResult(success=resp.status_code == 200, raw_response=data)
        except Exception as e:
            logger.error(f"即时回复文本失败: {e}")
            return SendResult(success=False, error_message=str(e))

    def reply_markdown(self, msg: InboundMessage, title: str, text: str) -> SendResult:
        """
        通过当前消息的 session_webhook 快速原地回复 Markdown 消息
        """
        if not msg.session_webhook:
            return SendResult(success=False, error_message="当前消息无 session_webhook，无法原地回复")

        headers = {"Content-Type": "application/json"}
        payload = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": text},
            "at": {"atUserIds": [msg.sender_staff_id] if msg.sender_staff_id else []}
        }
        try:
            resp = requests.post(msg.session_webhook, headers=headers, json=payload, timeout=8)
            data = resp.json() if resp.status_code == 200 else {}
            self.sent_count += 1
            return SendResult(success=resp.status_code == 200, raw_response=data)
        except Exception as e:
            logger.error(f"即时回复 Markdown 失败: {e}")
            return SendResult(success=False, error_message=str(e))

    def send_to_user(self, user_id: str, content: str, title: str = "", msg_type: str = "text") -> SendResult:
        """
        主动推送单聊消息到员工（通过 OpenAPI，需要已配置权限）
        """
        if msg_type == "markdown":
            res = self.openapi.send_to_user_markdown(user_id, title or "通知", content)
        else:
            res = self.openapi.send_to_user_text(user_id, content)
        if res.success:
            self.sent_count += 1
        return res

    def send_to_group(self, open_conversation_id: str, content: str, title: str = "", msg_type: str = "text") -> SendResult:
        """
        主动推送消息到群聊会话（通过 OpenAPI，需要群 openConversationId）
        """
        if msg_type == "markdown":
            res = self.openapi.send_to_group_markdown(open_conversation_id, title or "群通知", content)
        else:
            res = self.openapi.send_to_group_text(open_conversation_id, content)
        if res.success:
            self.sent_count += 1
        return res

    # ============ 运行生命周期管理 ============

    def start_in_background(self):
        """在独立后台守护线程中启动长连接监听"""
        if self.status in ("connecting", "connected"):
            logger.warning("Bot 已经在运行中，请勿重复启动")
            return

        self.status = "connecting"
        self.last_error = None

        def _thread_target():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                cred = Credential(self.client_id, self.client_secret)
                self._stream_client = _GracefulStreamClient(cred)

                # 挂载 ChatbotHandler
                bot_instance = self
                class CustomChatHandler(ChatbotHandler):
                    async def process(self, callback_message: CallbackMessage):
                        raw_data = callback_message.data
                        msg = InboundMessage.from_dict(raw_data)
                        if not bot_instance._is_duplicate_message(msg.msg_id):
                            bot_instance._dispatch_inbound(msg)
                        return AckMessage.STATUS_OK, "OK"

                self._stream_client.register_callback_handler(ChatbotMessage.TOPIC, CustomChatHandler())
                self.status = "connected"
                self.connected_at = time.time()
                self._loop.run_until_complete(self._stream_client.start())
            except Exception as e:
                self.status = "error"
                self.last_error = str(e)
                logger.error(f"Bot 运行异常退出: {e}")
            finally:
                self.status = "disconnected"
                self.connected_at = None

        self._thread = threading.Thread(target=_thread_target, daemon=True, name="DingTalkStreamThread")
        self._thread.start()

    def stop(self):
        """停止长连接监听"""
        if self._stream_client:
            self._stream_client.stopped = True
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(self._stream_client.close(), self._loop)
        self.status = "disconnected"
        self.connected_at = None
        logger.info("已请求停止钉钉 Stream 连接")
