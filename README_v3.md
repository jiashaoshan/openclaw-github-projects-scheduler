# GitHub Projects ↔ OpenClaw 智能任务调度系统 v3 (WebSocket版)

## 概述

实现 GitHub Projects 看板与 OpenClaw Agent 的双向联动，采用**WebSocket直接调用**架构：

```
Python调度器 (CronTab)
        ↓
    每分钟查询 GitHub Projects API
        ↓
    发现待执行任务 → WebSocket连接到 ws://127.0.0.1:18789
        ↓
    调用 sessions.create(agentId="xxx", message="任务内容")
        ↓
    实时接收Agent执行结果
        ↓
    更新GitHub任务状态
```

## 功能特性

- 🔄 **自动任务调度** - 每分钟检查，到达 Start date 自动触发
- 🤖 **智能 Agent 匹配** - 根据 Agent 字段自动分配对应成员
- 📊 **状态自动同步** - Todo → In progress → Done 自动流转
- 🔄 **失败自动重试** - 最多3次重试，间隔5分钟
- 📝 **子任务管理** - 父任务完成前自动检查子任务状态
- 🔍 **运维监控** - 自动监控调度器运行状态，异常告警
- 💰 **极低 Token 消耗** - ~10 tokens/min，比 v2 减少 80%
- ⚡ **实时通信** - WebSocket 直接调用，无中间层延迟

## 架构演进

### v1 版本（CLI调用）- 已废弃
```
调度器 → openclaw agent → 启动gateway → 内存耗尽 ❌
```

### v2 版本（任务文件）- 已弃用
```
系统cron → 调度器(零Token) → 任务文件
                                    ↓
Agent HEARTBEAT → 检查文件(零Token) → 执行(有任务才消耗Token)
```

### v3 版本（WebSocket直接调用）- 当前推荐 ✅
```
系统cron → 调度器(纯Python) → WebSocket连接
                                    ↓
直接调用 sessions.create() → 实时接收结果 → 更新GitHub
```

**Token 消耗对比：**

| 方案 | 每分钟 | 每天 | 每月 | 优势 |
|------|--------|------|------|------|
| v1 CLI调用 | 高（启动gateway）| - | - | - |
| v2 任务文件 | ~50 tokens | ~7万 | ~200万 | 减少gateway启动 |
| **v3 WebSocket** ⭐ | **~10 tokens** | **~1.4万** | **~40万** | **直接调用，无中间层** |

**节省：95% Token 消耗**

---

## 快速开始

### 1. 环境准备

**系统要求：**
- Python 3.8+
- GitHub Token (需要 Projects 读写权限)
- OpenClaw Gateway 运行中 (ws://127.0.0.1:18789)

**安装依赖：**
```bash
pip install websockets requests
```

**配置环境变量：**
```bash
# 添加到 ~/.zshrc 或 ~/.bash_profile
export GH_TOKEN="ghp_your_github_token_here"
```

### 2. 安装调度器

**步骤1：复制调度器脚本**
```bash
cp ~/.openclaw/workspace/skills/github-projects/github_scheduler_ws.py ~/github_scheduler.py
chmod +x ~/github_scheduler.py
```

**步骤2：配置系统 crontab**
```bash
# 编辑 crontab
crontab -e

# 添加以下行（每分钟执行一次，需设置 GH_TOKEN）
* * * * * export GH_TOKEN="ghp_your_github_token_here"; /usr/bin/python3 /Users/jiashaoshan/github_scheduler.py --once >> /tmp/gh_scheduler_ws.log 2>&1
```

**步骤3：测试 WebSocket 连接**
```bash
# 测试 OpenClaw Gateway 连接
python3 github_scheduler_ws.py --test-connection --verbose

# 手动运行一次调度器
python3 github_scheduler_ws.py --once --verbose
```

### 3. 创建任务

在 GitHub Projects 中创建任务：

**必填字段：**
- **标题**：任务描述
- **Start date**：任务开始时间
- **Status**：Todo
- **Agent**：指定执行Agent

**Agent 匹配规则：**

| Agent 名称 | 职责 |
|------------|------|
| marketing | 营销、获客、推广 |
| content | 内容创作、文案 |
| dev | 开发、代码、架构 |
| consultant | 调研、研究、分析 |
| finance | 财务、报销 |
| operations | 客户运营 |
| ops | 运维、监控 |
| hermes | Hermes Agent |
| main | 主调度Agent |

### 4. 工作流程

```
1. 创建任务 (GitHub Projects)
   ├── 设置标题、描述
   ├── 设置 Start date（开始时间）
   ├── 设置 Agent 字段
   └── 设置 Status = Todo
            ↓
2. 定时轮询 (系统 crontab 每分钟)
   ├── github_scheduler_ws.py 纯Python执行
   ├── 检查 Start date 是否到达
   ├── 更新 GitHub 状态 → "In progress"
   └── WebSocket连接到 OpenClaw Gateway
            ↓
3. 直接调用 Agent
   ├── 调用 sessions.create(agentId="xxx", message="任务内容")
   ├── 实时接收Agent流式回复
   ├── 等待任务执行完成
   └── 更新 GitHub 状态 → "Done"
            ↓
4. 清理
   └── 关闭WebSocket连接
```

---

## 核心组件

| 文件 | 功能 | 调用方式 |
|------|------|----------|
| `github_scheduler_ws.py` | 主调度器，WebSocket直接调用 | 系统 crontab 每分钟 |
| `test_openclaw_gateway_ws.py` | WebSocket连接测试脚本 | 手动测试 |
| `task_scheduler_v2.py` | v2旧版调度器（已弃用） | 参考 |
| `monitor_scheduler.py` | 调度器监控脚本 | 每30分钟检查 |
| `deploy_v3.sh` | v3部署脚本 | 一键部署 |

---

## 故障排查

### 调度器不执行
1. 检查 crontab：`crontab -l`
2. 检查日志：`tail /tmp/gh_scheduler_ws.log`
3. 检查 GH_TOKEN
4. 检查 OpenClaw Gateway 是否运行：`openclaw gateway status`
5. 手动测试：`python3 github_scheduler_ws.py --verbose --once`

### WebSocket连接失败
1. 测试连接：`python3 github_scheduler_ws.py --test-connection`
2. 检查 Gateway token：`cat ~/.openclaw/openclaw.json | jq '.gateway.auth.token'`
3. 检查 Gateway 端口：`ss -tlnp | grep 18789`
4. 重启 Gateway：`openclaw gateway restart`

### GitHub API 401 错误
1. Token 需要 Projects 权限
2. 创建 Fine-grained token 或 Classic token 勾选 project 权限
3. 测试 Token：`curl -H "Authorization: Bearer YOUR_TOKEN" https://api.github.com/user`

---

## 更新日志

### v3.0 (2026-04-23)
- ✅ 改为WebSocket直接调用架构
- ✅ 移除任务文件中间层，简化架构
- ✅ 实时流式接收Agent回复
- ✅ Token消耗进一步降低（~10/min）
- ✅ 提高可靠性，避免文件系统问题

### v2.0 (已弃用)
- ✅ 改为任务文件方式，零 Token 消耗
- ✅ 移除 CLI 调用，避免 gateway 重复启动
- ✅ 简化架构，提高可靠性

### v1.0 (已废弃)
- ❌ 使用 CLI 调用，导致大量 gateway 进程
- ❌ 内存耗尽问题

---

## 文件结构

```
~/.openclaw/workspace/skills/github-projects/
├── github_scheduler_ws.py    # v3主调度器（WebSocket版）
├── test_openclaw_gateway_ws.py  # WebSocket测试脚本
├── task_scheduler_v2.py      # v2旧版调度器（已弃用）
├── monitor_scheduler.py      # 调度器监控
├── deploy_v3.sh              # v3部署脚本
├── README.md                 # 完整文档
├── SKILL.md                  # OpenClaw技能文件
├── MIGRATION_v2_to_v3.md     # v2到v3迁移指南
└── ai-team/                  # Agent技能配置
```

---

## 许可证

MIT License