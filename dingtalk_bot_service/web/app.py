"""
FastAPI 后台服务
管理钉钉 Bot 实例、配置持久化、实时 WebSocket 监控与手动测试接口
"""
import os
import json
import time
import asyncio
from typing import List, Dict, Any, Optional
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from core import DingTalkBot, InboundMessage, SendResult

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="DingTalk Bot Controller", version="1.0.0")

# 全局共享状态
bot_instance: Optional[DingTalkBot] = None
connected_websockets: List[WebSocket] = []
recent_logs: List[Dict[str, Any]] = []
recent_messages: List[Dict[str, Any]] = []


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        default_cfg = {
            "client_id": "",
            "client_secret": "",
            "auto_reply": True,
            "auto_reply_template": "[钉钉自动回复] 收到消息: {content}",
            "web_port": 8800
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default_cfg, f, indent=2, ensure_ascii=False)
        return default_cfg
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


async def broadcast_event(event_type: str, data: Any):
    """向所有在线 WebSocket 客户端广播事件"""
    payload = {
        "type": event_type,
        "timestamp": time.strftime("%H:%M:%S"),
        "data": data
    }
    # 存入近期历史
    if event_type in ("inbound", "outbound"):
        recent_messages.append(payload)
        if len(recent_messages) > 100:
            recent_messages.pop(0)
    elif event_type == "log":
        recent_logs.append(payload)
        if len(recent_logs) > 200:
            recent_logs.pop(0)

    # 发送
    dead_sockets = []
    for ws in connected_websockets:
        try:
            await ws.send_json(payload)
        except Exception:
            dead_sockets.append(ws)
    for ws in dead_sockets:
        if ws in connected_websockets:
            connected_websockets.remove(ws)


def broadcast_event_sync(event_type: str, data: Any):
    """线程安全地在事件循环中调度广播"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(broadcast_event(event_type, data), loop)
    except Exception:
        pass


def setup_bot_instance(cfg: dict) -> DingTalkBot:
    """创建并绑定 Bot 实例"""
    global bot_instance
    if bot_instance:
        bot_instance.stop()

    bot = DingTalkBot(
        client_id=cfg.get("client_id", ""),
        client_secret=cfg.get("client_secret", ""),
        auto_reply=cfg.get("auto_reply", True),
        auto_reply_template=cfg.get("auto_reply_template", "收到消息：{content}")
    )

    # 挂载消息监听监控钩子
    @bot.on_message
    def on_inbound(msg: InboundMessage):
        broadcast_event_sync("inbound", {
            "msg_id": msg.msg_id,
            "sender_nick": msg.sender_nick,
            "sender_id": msg.sender_id,
            "sender_staff_id": msg.sender_staff_id,
            "chat_type": "单聊/私聊" if msg.is_direct_chat else f"群聊({msg.conversation_title or msg.conversation_id})",
            "content": msg.content,
            "session_webhook": msg.session_webhook,
            "is_at_all": msg.is_at_all,
            "is_in_at_list": msg.is_in_at_list,
            "created_at": time.strftime("%H:%M:%S")
        })

    bot_instance = bot
    return bot


# ============ API 路由 ============

class ConfigModel(BaseModel):
    client_id: str
    client_secret: str
    auto_reply: bool = True
    auto_reply_template: str = "[钉钉自动回复] 收到消息: {content}"
    web_port: int = 8800


class SendTestModel(BaseModel):
    target_type: str  # "user" | "group" | "webhook"
    target: str       # user_id / open_conversation_id / session_webhook
    content: str
    title: Optional[str] = "测试通知"
    msg_type: str = "text"  # "text" | "markdown"


@app.get("/api/config")
def get_config_endpoint():
    cfg = load_config()
    # 稍微隐藏密码中间位展示
    masked_cfg = dict(cfg)
    return masked_cfg


@app.post("/api/config")
def save_config_endpoint(model: ConfigModel):
    cfg = model.model_dump()
    save_config(cfg)
    # 如果 bot 存在，热更新配置
    if bot_instance:
        bot_instance.client_id = cfg["client_id"]
        bot_instance.client_secret = cfg["client_secret"]
        bot_instance.auto_reply = cfg["auto_reply"]
        bot_instance.auto_reply_template = cfg["auto_reply_template"]
        bot_instance.openapi.client_id = cfg["client_id"]
        bot_instance.openapi.client_secret = cfg["client_secret"]
    broadcast_event_sync("log", {"level": "info", "text": "配置已更新并保存"})
    return {"status": "ok", "message": "配置保存成功"}


@app.get("/api/bot/status")
def get_bot_status_endpoint():
    if not bot_instance:
        return {
            "status": "disconnected",
            "connected_at": None,
            "last_inbound_at": None,
            "received_count": 0,
            "sent_count": 0,
            "last_error": None
        }
    return {
        "status": bot_instance.status,
        "connected_at": bot_instance.connected_at,
        "last_inbound_at": bot_instance.last_inbound_at,
        "received_count": bot_instance.received_count,
        "sent_count": bot_instance.sent_count,
        "last_error": bot_instance.last_error
    }


@app.post("/api/bot/start")
def start_bot_endpoint():
    global bot_instance
    cfg = load_config()
    if not cfg.get("client_id") or not cfg.get("client_secret"):
        raise HTTPException(status_code=400, detail="请先在配置中填写 Client ID (AppKey) 和 Client Secret (AppSecret)")

    if not bot_instance:
        setup_bot_instance(cfg)
    
    bot_instance.start_in_background()
    broadcast_event_sync("log", {"level": "info", "text": "正在连接钉钉 Stream 长连接网关..."})
    return {"status": "ok", "message": "已触发长连接启动"}


@app.post("/api/bot/stop")
def stop_bot_endpoint():
    global bot_instance
    if bot_instance:
        bot_instance.stop()
        broadcast_event_sync("log", {"level": "warn", "text": "已断开钉钉长连接"})
    return {"status": "ok", "message": "已断开连接"}


@app.post("/api/bot/send")
def send_test_message_endpoint(req: SendTestModel):
    global bot_instance
    if not bot_instance:
        raise HTTPException(status_code=400, detail="Bot 实例尚未初始化，请先启动或配置")

    if not req.target or not req.content:
        raise HTTPException(status_code=400, detail="目标与发送内容不能为空")

    res: SendResult
    if req.target_type == "webhook":
        # 伪造一个带 session_webhook 的临时 InboundMessage 进行测试回复
        dummy_msg = InboundMessage(
            msg_id="test_" + str(int(time.time())),
            msg_type="text",
            conversation_type="1",
            conversation_id="",
            session_webhook=req.target
        )
        if req.msg_type == "markdown":
            res = bot_instance.reply_markdown(dummy_msg, req.title or "测试Markdown", req.content)
        else:
            res = bot_instance.reply_text(dummy_msg, req.content)
    elif req.target_type == "user":
        res = bot_instance.send_to_user(req.target, req.content, req.title or "通知", req.msg_type)
    elif req.target_type == "group":
        res = bot_instance.send_to_group(req.target, req.content, req.title or "通知", req.msg_type)
    else:
        raise HTTPException(status_code=400, detail=f"未知的目标类型: {req.target_type}")

    broadcast_event_sync("outbound", {
        "target_type": req.target_type,
        "target": req.target,
        "content": req.content,
        "msg_type": req.msg_type,
        "success": res.success,
        "error": res.error_message,
        "created_at": time.strftime("%H:%M:%S")
    })

    if res.success:
        return {"status": "ok", "message": "发送成功", "result": res.raw_response}
    else:
        return {"status": "error", "message": f"发送失败: {res.error_message}", "result": res.raw_response}


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    connected_websockets.append(websocket)
    try:
        # 发送已有近期历史
        for item in recent_messages[-30:]:
            await websocket.send_json(item)
        for log in recent_logs[-20:]:
            await websocket.send_json(log)

        while True:
            # 保持心跳连接
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in connected_websockets:
            connected_websockets.remove(websocket)


# 挂载前端静态文件
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index_page():
    return FileResponse(STATIC_DIR / "index.html")
