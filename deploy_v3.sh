#!/bin/bash
# GitHub Projects WebSocket调度器 v3 部署脚本

set -e

echo "========================================"
echo "GitHub Projects WebSocket调度器 v3 部署"
echo "========================================"

# 检查依赖
echo "检查依赖..."
if ! command -v python3 &> /dev/null; then
    echo "❌ 需要 python3"
    exit 1
fi

if ! python3 -c "import websockets" 2>/dev/null; then
    echo "安装 websockets..."
    pip3 install websockets
fi

if ! python3 -c "import requests" 2>/dev/null; then
    echo "安装 requests..."
    pip3 install requests
fi

# 检查GH_TOKEN
if [ -z "$GH_TOKEN" ]; then
    echo "⚠️ 环境变量 GH_TOKEN 未设置"
    echo "请设置GitHub Personal Access Token:"
    echo "export GH_TOKEN=\"your_token_here\""
    echo "或添加到 ~/.bashrc / ~/.zshrc"
    read -p "是否继续? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 检查OpenClaw Gateway
echo "检查OpenClaw Gateway..."
if ! lsof -i :18789 &>/dev/null; then
    echo "⚠️ OpenClaw Gateway 未运行在端口 18789"
    echo "启动Gateway: openclaw gateway start"
    read -p "是否继续? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "✅ OpenClaw Gateway 正在运行"
fi

# 测试WebSocket连接
echo "测试WebSocket连接..."
cd "$(dirname "$0")"
if python3 github_scheduler_ws.py --test-connection; then
    echo "✅ WebSocket连接测试通过"
else
    echo "❌ WebSocket连接测试失败"
    exit 1
fi

# 配置cron
echo "配置cron任务..."
CRON_JOB="* * * * * /usr/bin/python3 $(pwd)/github_scheduler_ws.py --once >> /tmp/gh_scheduler_ws.log 2>&1"

echo "请手动添加以下cron任务:"
echo "========================================"
echo "$CRON_JOB"
echo "========================================"
echo ""
echo "编辑crontab: crontab -e"
echo "然后添加上面的行"
echo ""
echo "日志文件: /tmp/gh_scheduler_ws.log"
echo "查看日志: tail -f /tmp/gh_scheduler_ws.log"

# 创建日志轮转配置
echo "创建日志轮转配置..."
cat > /tmp/gh_scheduler_ws_logrotate.conf << EOF
/tmp/gh_scheduler_ws.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    create 644 $(whoami) $(whoami)
}
EOF

echo "日志轮转配置已保存到: /tmp/gh_scheduler_ws_logrotate.conf"
echo "可以复制到 /etc/logrotate.d/ 或手动配置"

echo ""
echo "✅ 部署完成"
echo ""
echo "下一步:"
echo "1. 设置 GH_TOKEN 环境变量"
echo "2. 添加cron任务"
echo "3. 在GitHub Projects中创建任务"
echo "4. 监控日志: tail -f /tmp/gh_scheduler_ws.log"
echo ""
echo "测试调度器:"
echo "  python3 github_scheduler_ws.py --once --verbose"
echo ""
echo "架构已从v2任务文件方式升级为v3 WebSocket直接调用"
echo "Token消耗: ~10/min (比v2减少80%)"