@echo off
chcp 65001 >nul
title 钉钉机器人控制台

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [INFO] 未检测到虚拟环境，正在创建 .venv...
    python -m venv .venv
    echo [INFO] 正在安装依赖项...
    .venv\Scripts\pip install -r requirements.txt
)

echo [INFO] 正在启动钉钉机器人控制台...
.venv\Scripts\python main.py

pause
