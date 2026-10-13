# 钉钉机器人监听与发送独立服务 (Python)

本项目将钉钉机器人的 **Stream 长连接消息监听** 与 **消息主动/被动发送** 能力完全从 OpenClaw 插件中解耦并独立出来，专为方便移植整合到现有 Python 机器人项目（如已有微信机器人）而设计。

---

## 🌟 核心特色

1. **零公网 IP / 零 Webhook 域名需求**：采用钉钉官方 Stream 模式（WebSocket 长连接），内网/本地开发环境即可秒级接收群聊与私聊消息。
2. **完全解耦的可移植内核 (`core/`)**：核心类 `DingTalkBot` 不依赖任何 Web 框架或额外宿主，可像类库一样直接 `import` 复制到已有微信项目中。
3. **开箱即用的现代化 Web 控制台 (`web/`)**：
   - 网页在线配置与持久化 AppKey / AppSecret。
   - 一键启动/断开连接与实时健康状态展示。
   - 实时消息流水与系统日志（基于 WebSocket 推送）。
   - 手动测试面板：即时测试回复、主动推送到单聊/群聊。

---

## 📁 目录结构

```text
dingtalk_bot_service/
├── core/                        # ★【完全独立的核心能力包，直接拷入其他项目】
│   ├── __init__.py              # 导出 DingTalkBot, InboundMessage, SendResult
│   ├── bot.py                   # 核心 Bot 类：长连接生命周期、去重、回调分发、回复
│   ├── models.py                # 消息实体 InboundMessage、发送结果 SendResult
│   └── openapi.py               # 钉钉 OpenAPI 客户端（Token缓存、主动推群/推人）
├── web/                         # Web 可视化控制台
│   ├── app.py                   # FastAPI 服务与 WebSocket 流
│   └── static/index.html        # 响应式控制台前端界面
├── config.json                  # 本地持久化凭证与配置
├── main.py                      # 独立启动脚本
├── run.bat                      # Windows 一键启动脚本
└── requirements.txt             # 依赖声明
```

---

## 🚀 快速启动与体验

### 方式 1：双击一键运行（Windows）
直接双击运行 [run.bat](file:///d:/WorkSpace/Python/dingtalk-openclaw-connector/dingtalk_bot_service/run.bat)。
脚本会自动检测虚拟环境、安装依赖并启动服务。

### 方式 2：命令行运行
```bash
# 1. 激活虚拟环境
.\.venv\Scripts\activate

# 2. 启动服务
python main.py
```

启动后在浏览器打开：
👉 **http://127.0.0.1:8800**

---

## ⚙️ 钉钉机器人配置指引（3 分钟）

1. 登录 [钉钉开发者后台](https://open-dev.dingtalk.com/)。
2. 点击 **应用开发 -> 企业内部开发 -> 创建应用**（类型选“钉钉应用”）。
3. 进入应用详情页，在左侧导航点击 **添加应用能力 -> 机器人**，点击添加。
4. 在机器人配置中：
   - **消息接收模式**：务必选择 **Stream 模式**（无需配置回调 URL）。
   - 点击保存。
5. 在左侧导航点击 **凭证与基础信息**，获取：
   - **AppKey (Client ID)**
   - **AppSecret (Client Secret)**
6. 打开控制台页面 `http://127.0.0.1:8800`，填入这两个值并点击 **保存配置** -> **启动长连接** 即可！
7. （测试）：在钉钉中将该机器人添加到测试群或单聊，发送文字即可在控制台看到实时流水和自动回复。

---

## 🧩 移植到微信项目的极简示例（推荐）

只需将 `core/` 整个文件夹复制到你的现有微信项目中即可使用，代码范例如下：

```python
from core import DingTalkBot, InboundMessage

# 1. 初始化钉钉机器人实例
ding_bot = DingTalkBot(
    client_id="YOUR_APP_KEY",
    client_secret="YOUR_APP_SECRET",
    auto_reply=False  # 关闭默认回显，使用你的自定义业务处理
)

# 2. 注册消息监听回调（与你的微信消息接收逻辑对齐）
@ding_bot.on_message
def handle_dingtalk_message(msg: InboundMessage):
    print(f"收到钉钉消息: [{msg.sender_nick}] {msg.content}")
    
    # ── 这里调用你现有的微信业务逻辑 / 统一 AI 处理函数 ──
    # reply_text = your_ai_agent_process(msg.content)
    reply_text = f"统一大脑已处理: {msg.content}"
    
    # 原地即时回复（通过单次有效的 session_webhook，无需额外权限）
    if msg.session_webhook:
        ding_bot.reply_text(msg, reply_text)

# 3. 后台启动长连接（不阻塞微信机器人的事件循环与主线程）
ding_bot.start_in_background()

# 4. 主动发送示例（如果业务需要主动给钉钉员工推送消息）：
# ding_bot.send_to_user("staff_id_123", "来自系统的待办通知")
```

---

## 🛠️ API 速查表

### 消息对象 `InboundMessage`
- `msg.content`: 消息文本内容
- `msg.sender_nick`: 发送人昵称
- `msg.sender_staff_id`: 发送人工号 / 企业 StaffId
- `msg.is_direct_chat`: 是否为单聊私聊 (`bool`)
- `msg.is_group_chat`: 是否为群聊 (`bool`)
- `msg.conversation_id`: 会话 ID
- `msg.session_webhook`: 即时回复 Webhook URL（最核心，用于原地回复）

### 常用发送方法
- `bot.reply_text(msg, "内容")`：通过 `session_webhook` 原地被动回复文本
- `bot.reply_markdown(msg, "标题", "Markdown文本")`：原地被动回复 Markdown
- `bot.send_to_user("staffId", "内容")`：主动推送单聊消息到指定员工
- `bot.send_to_group("cidXXX", "内容")`：主动推送群聊消息到指定群会话
