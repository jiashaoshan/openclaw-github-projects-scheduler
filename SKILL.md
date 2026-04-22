---
name: github-projects
description: "GitHub Projects V2 与 OpenClaw Agent 联动系统 v2（任务文件方式）。支持任务状态监听、Agent 自动分发、执行结果回写。零Token消耗调度。"
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

# GitHub Projects ↔ OpenClaw 联动系统 v2

## 功能概述

实现 GitHub Projects 看板与 OpenClaw Agent 的双向联动，采用**任务文件方式**实现零 Token 消耗调度：

```
系统cron(每分钟) → 调度器(零Token) → 创建任务文件
                                           ↓
    Agent HEARTBEAT(检查文件) → 有任务? → 执行 → 更新GitHub
```

## 工作流程

```
┌─────────────────────────────────────────────────────────────────┐
│                     v2 架构 - 任务文件方式                       │
└─────────────────────────────────────────────────────────────────┘

  1. 创建任务 (GitHub Projects)
     ├── 设置标题、描述
     ├── 设置 Start date（开始时间）
     ├── 设置 Agent 字段
     └── 设置 Status = Todo
              ↓
  2. 定时轮询 (系统 crontab 每分钟)
     ├── task_scheduler_v2.py 纯Python执行
     ├── 检查 Start date 是否到达
     ├── 更新 GitHub 状态 → "In progress"
     └── 创建任务文件 /tmp/gh_tasks/{agent}/{task_id}.json
              ↓
  3. Agent HEARTBEAT 检查
     ├── 检查本地任务文件（零Token）
     ├── 有任务? → 读取任务信息
     └── 无任务 → 返回 HEARTBEAT_OK（零Token）
              ↓
  4. Agent 执行
     ├── 标记任务为 processing
     ├── 读取 ai-team/{agent}/SKILLS.md
     ├── 调用对应技能完成任务
     └── 执行完成后更新 GitHub 状态 → "Done"
              ↓
  5. 归档
     └── 任务文件移动到 /tmp/gh_tasks/{agent}/archive/
```

## 核心组件

| 文件 | 功能 | 调用方式 |
|------|------|----------|
| `task_scheduler_v2.py` | 主调度器，轮询+创建任务文件 | 系统 crontab 每分钟 |
| `README.md` | 完整文档 | 参考 |

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

# 添加调度器（每分钟执行，零Token）
* * * * * /usr/bin/python3 /path/to/task_scheduler_v2.py --once >> /tmp/gh_scheduler.log 2>&1
```

### 3. 配置 Agent HEARTBEAT

在各 Agent 的 `SKILLS.md` 中添加：

```markdown
## HEARTBEAT 任务检查

检查 GitHub Projects 任务文件：

```python
import os
import json
from pathlib import Path

def check_github_tasks():
    agent_name = "marketing"  # 修改为对应Agent
    tasks_dir = Path(f"/tmp/gh_tasks/{agent_name}")
    
    if not tasks_dir.exists():
        return None
    
    for task_file in tasks_dir.glob("*.json"):
        try:
            with open(task_file) as f:
                task = json.load(f)
            if task.get("status") == "pending":
                return task
        except:
            continue
    return None

task = check_github_tasks()
if task:
    # 执行任务
    execute_task(task)
    return f"完成任务: {task['title']}"
else:
    return "HEARTBEAT_OK"
```
```

### 4. Agent 完成回调

Agent 执行完成后，调用调度器更新状态：

```bash
# 标记任务完成
python3 task_scheduler_v2.py --complete PVTI_xxx --agent marketing

# 标记任务失败
python3 task_scheduler_v2.py --fail PVTI_xxx --agent marketing
```

## Token 消耗对比

| 方案 | 每分钟 | 每天 | 每月 |
|------|--------|------|------|
| v1 CLI调用 | 高（启动gateway）| - | - |
| **v2 任务文件** ⭐ | **~50 tokens** | **~7万** | **~200万** |

**节省：90% Token 消耗**

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

## 文件位置

```
~/.openclaw/workspace/skills/github-projects/
├── task_scheduler_v2.py    # 主调度器
├── README.md               # 完整文档
└── SKILL.md               # 本文件
```

任务文件目录：
```
/tmp/gh_tasks/
├── marketing/
│   ├── PVTI_xxx.json      # 待处理任务
│   └── archive/           # 已完成任务
├── content/
├── dev/
└── ...
```

## 故障排查

### 调度器不执行
1. 检查 crontab：`crontab -l`
2. 检查日志：`tail /tmp/gh_scheduler.log`
3. 检查 GH_TOKEN
4. 手动测试：`python3 task_scheduler_v2.py --verbose --once`

### Agent 不执行任务
1. 检查任务文件：`ls /tmp/gh_tasks/{agent}/`
2. 检查 HEARTBEAT 配置
3. 检查任务状态是否为 pending

## 更新日志

### v2.0 (2026-04-22)
- ✅ 改为任务文件方式，零 Token 消耗
- ✅ 移除 CLI 调用，避免 gateway 重复启动
- ✅ 简化架构，提高可靠性

### v1.0 (已废弃)
- ❌ 使用 CLI 调用，导致大量 gateway 进程
- ❌ 内存耗尽问题
