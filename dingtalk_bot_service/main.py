"""
钉钉机器人与管理控制台主入口
运行此文件即可一键启动 Web 控制台与后台监听服务
"""
import sys
import os
from pathlib import Path
import uvicorn

# 确保 core 和 web 模块能正常导入
# 确保 Windows 下控制台编码为 UTF-8
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from web.app import app, load_config, setup_bot_instance


def main():
    cfg = load_config()
    port = int(cfg.get("web_port", 8800))
    host = "127.0.0.1"

    print("=" * 65)
    print(" [DingTalk Bot] 钉钉机器人监听与控制服务已就绪！")
    print(f" [Web URL] 控制台访问地址: http://{host}:{port}")
    print(f" [Core Module] 核心可移植模块位置: {CURRENT_DIR / 'core'}")
    print("=" * 65)

    # 如果已经配置了 Client ID 与 Secret，预初始化 bot 实例
    if cfg.get("client_id") and cfg.get("client_secret"):
        bot = setup_bot_instance(cfg)
        print(" [Auth] 检测到已存在配置凭证，正在尝试自动建立长连接...")
        bot.start_in_background()
    else:
        print(" [Notice] 尚未配置 AppKey / AppSecret，请打开上方网页进行配置。")

    # 启动 Uvicorn Web 服务
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
