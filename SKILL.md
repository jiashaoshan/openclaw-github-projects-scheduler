---
name: github-projects
description: "GitHub Projects V2 与 OpenClaw Agent 联动系统 v3（WebSocket版）。支持任务状态监听、Agent 自动分发、执行结果回写。WebSocket直接调用架构。"
user-invocable: true
metadata:
  {
    "openclaw":
      {
        "requires": { "bins": ["python3"] },
        "primaryEnv": "GH_TOKEN",
      },
  }
---

# GitHub Projects ↔ OpenClaw 联动系统 v3 (WebSocket版)

## 功能概述

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

## 架构演进

| 版本 | 架构 | Token消耗 | 复杂度 | 可靠性 |
|------|------|-----------|--------|--------|
| v1 | CLI调用 | 高 | 中 | 低 |
| v2 | 任务文件 | ~50/min | 高 | 中 |
| **v3** | **WebSocket直接调用** | **~10/min** | **低** | **高** |

## 工作流程

```
┌─────────────────────────────────────────────────────────────────┐
│                     v3 架构 - WebSocket直接调用                  │
└─────────────────────────────────────────────────────────────────┘

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

## 核心组件

| 文件 | 功能 | 调用方式 |
|------|------|----------|
| `github_scheduler_ws.py` | 主调度器，WebSocket直接调用 | 系统 crontab 每分钟 |
| `test_openclaw_gateway_ws.py` | WebSocket连接测试脚本 | 手动测试 |
| `task_scheduler_v2.py` | v2旧版调度器（已弃用） | 参考 |

## 使用方法

### 1. 创建任务

在 GitHub Projects 中创建任务：

**必填字段：**
- **标题**：任务描述
- **Start date**：任务开始时间
- **Status**：Todo
- **Agent**：指定执行Agent

### 2. 配置系统 Cron

```bash
# 编辑 crontab
crontab -e

# 添加新的WebSocket调度器（每分钟执行）
* * * * * /usr/bin/python3 /path/to/github_scheduler_ws.py --once >> /tmp/gh_scheduler_ws.log 2>&1

# 移除旧的调度器（如果存在）
# * * * * * /usr/bin/python3 /path/to/task_scheduler_v2.py --once >> /tmp/gh_scheduler.log 2>&1
```

### 3. 测试连接

```bash
# 测试WebSocket连接
python3 github_scheduler_ws.py --test-connection --verbose

# 手动运行一次调度器
python3 github_scheduler_ws.py --once --verbose
```

## Token 消耗对比

| 方案 | 每分钟 | 每天 | 每月 | 优势 |
|------|--------|------|------|------|
| v1 CLI调用 | 高（启动gateway）| - | - | - |
| v2 任务文件 | ~50 tokens | ~7万 | ~200万 | 减少gateway启动 |
| **v3 WebSocket** | **~10 tokens** | **~1.4万** | **~40万** | **直接调用，无中间层** |

**节省：95% Token 消耗**

## Agent 匹配规则

Agent 根据 GitHub Projects 中的 "Agent" 字段匹配：

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

## 文件位置

```
~/.openclaw/workspace/skills/github-projects/
├── github_scheduler_ws.py    # v3主调度器（WebSocket版）
├── test_openclaw_gateway_ws.py  # WebSocket测试脚本
├── task_scheduler_v2.py      # v2旧版调度器（已弃用）
├── README.md                 # 完整文档
└── SKILL.md                 # 本文件
```

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

## 更新日志

### v3.0 (2026-04-22)
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
