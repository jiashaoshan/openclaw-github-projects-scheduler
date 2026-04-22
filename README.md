# GitHub Projects 自动任务调度系统 v2

## 概述

实现 GitHub Projects 与 OpenClaw AI 团队的自动联动，采用**任务文件方式**实现零 Token 消耗调度：

```
系统cron(每分钟) → 调度器(零Token) → 创建任务文件
                                           ↓
    Agent HEARTBEAT(检查文件) → 有任务? → 执行 → 更新GitHub
```

## 功能特性

- 🔄 **自动任务调度** - 每分钟检查，到达 Start date 自动创建任务文件
- 🤖 **智能 Agent 匹配** - 根据任务标题自动分配对应 Agent
- 📊 **状态自动同步** - Todo → In progress → Done 自动流转
- 🔄 **失败自动重试** - 最多3次重试，间隔5分钟
- 📝 **子任务管理** - 父任务完成前自动检查子任务状态
- 🔍 **运维监控** - 自动监控调度器运行状态，异常告警
- 💰 **零 Token 轮询** - 调度器纯 Python，Agent 检查文件零 Token

## 架构对比

### v1 版本（CLI调用）- 已废弃
```
调度器 → openclaw agent → 启动gateway → 内存耗尽 ❌
```

### v2 版本（任务文件）- 当前推荐 ✅
```
系统cron → 调度器(零Token) → 任务文件
                                    ↓
Agent HEARTBEAT → 检查文件(零Token) → 执行(有任务才消耗Token)
```

**Token 消耗对比：**

| 方案 | 每分钟 | 每天 | 每月 |
|------|--------|------|------|
| v1 CLI调用 | 高（启动大量gateway）| - | - |
| **v2 任务文件** ⭐ | **~50 tokens** | **~7万** | **~200万** |

---

## 快速开始

### 1. 环境准备

**系统要求：**
- Python 3.8+
- GitHub Token (需要 Projects 读写权限)

**配置环境变量：**
```bash
# 添加到 ~/.zshrc 或 ~/.bash_profile
export GH_TOKEN="ghp_your_github_token_here"
```

### 2. 安装调度器

**步骤1：复制调度器脚本**
```bash
cp ~/.openclaw/workspace/skills/github-projects/task_scheduler_v2.py ~/task_scheduler.py
chmod +x ~/task_scheduler.py
```

**步骤2：配置系统 crontab**
```bash
# 编辑 crontab
crontab -e

# 添加以下行（每分钟执行一次）
* * * * * /usr/bin/python3 /Users/jiashaoshan/task_scheduler.py --once >> /tmp/gh_scheduler.log 2>&1
```

**步骤3：配置 Agent HEARTBEAT**

修改各 Agent 的 `SKILLS.md`，添加任务检查逻辑：

```markdown
## HEARTBEAT 任务检查

检查 GitHub Projects 任务文件并执行：

```python
import os
import json
from pathlib import Path

def check_github_tasks():
    """检查是否有待处理的任务"""
    agent_name = "marketing"  # 修改为对应Agent名称
    tasks_dir = Path(f"/tmp/gh_tasks/{agent_name}")
    
    if not tasks_dir.exists():
        return None
    
    # 查找pending状态的任务文件
    for task_file in tasks_dir.glob("*.json"):
        try:
            with open(task_file) as f:
                task = json.load(f)
            if task.get("status") == "pending":
                return task
        except:
            continue
    
    return None

def execute_task(task):
    """执行任务"""
    item_id = task["item_id"]
    title = task["title"]
    body = task["body"]
    
    # 1. 标记任务为处理中
    mark_task_processing(item_id)
    
    # 2. 执行任务（调用对应技能）
    result = do_actual_work(title, body)
    
    # 3. 更新GitHub状态
    update_github_status(item_id, success=True)
    
    return result

# HEARTBEAT入口
task = check_github_tasks()
if task:
    result = execute_task(task)
    return f"完成任务: {task['title']}\n结果: {result}"
else:
    return "HEARTBEAT_OK"
```
```

### 3. 配置 Agent 任务执行

**Agent 执行流程：**

1. **HEARTBEAT 检查任务文件**（零 Token）
2. **有任务时读取任务信息**
3. **标记任务为 processing**
4. **调用对应技能执行任务**
5. **更新 GitHub Projects 状态为 Done**
6. **归档任务文件**

**示例代码（Agent端）：**

```python
import subprocess
from pathlib import Path

# 更新GitHub状态
def update_github_status(item_id: str, success: bool = True):
    scheduler_path = "~/.openclaw/workspace/skills/github-projects/task_scheduler_v2.py"
    action = "--complete" if success else "--fail"
    subprocess.run([
        "python3", scheduler_path, action, item_id, "--agent", "marketing"
    ])

# 标记任务处理中
def mark_task_processing(item_id: str):
    task_file = Path(f"/tmp/gh_tasks/marketing/{item_id.replace(':', '_')}.json")
    if task_file.exists():
        import json
        with open(task_file) as f:
            task = json.load(f)
        task["status"] = "processing"
        task["started_at"] = datetime.now().isoformat()
        with open(task_file, 'w') as f:
            json.dump(task, f)
```

---

## 详细配置

### GitHub Projects 字段配置

确保项目有以下字段：

| 字段名 | 类型 | 说明 |
|--------|------|------|
| **Status** | Single select | Todo, In progress, Done, Failed |
| **Agent** | Single select | marketing, content, dev, consultant, finance, operations, ops |
| **Start date** | Date | 任务开始日期 |

### Agent 字段选项ID

```python
AGENT_OPTIONS = {
    "marketing": "66454f73",
    "content": "607e4b84",
    "dev": "6cd51e5a",
    "consultant": "1eb83706",
    "finance": "c3710345",
    "operations": "9250d027",
    "ops": "c54bb062",
    "hermes": "461bd124",
    "main": "ee8306f2"
}
```

### 状态字段选项ID

```python
STATUS_TODO = "f75ad846"
STATUS_IN_PROGRESS = "47fc9ee4"
STATUS_DONE = "98236657"
STATUS_FAILED = "a2aba7a8"
```

---

## 使用示例

### 创建任务

1. 在 GitHub Projects 创建任务
2. 设置 **Agent** 字段（如 marketing）
3. 设置 **Start date** 为今天或过去
4. 设置 **Status** 为 **Todo**

### 任务自动流转

```
创建任务(Status=Todo, Start date=今天)
    ↓ 调度器每分钟检查
到达开始时间 → 创建任务文件 /tmp/gh_tasks/marketing/task.json
    ↓ 更新GitHub
Status → In progress
    ↓ Agent HEARTBEAT检查
发现任务文件 → 执行
    ↓ 完成后
Status → Done
    ↓ 归档
任务文件移动到 /tmp/gh_tasks/marketing/archive/
```

---

## 运维监控

### 查看调度器日志
```bash
tail -f /tmp/gh_scheduler.log
```

### 查看任务文件
```bash
# 查看所有待处理任务
ls -la /tmp/gh_tasks/*/

# 查看特定Agent任务
cat /tmp/gh_tasks/marketing/*.json
```

### 手动触发检查
```bash
python3 ~/task_scheduler.py --verbose --once
```

### 手动标记任务完成
```bash
# Agent执行完成后调用
python3 ~/task_scheduler.py --complete PVTI_xxx --agent marketing
```

---

## 故障排查

### 调度器不执行
1. 检查 crontab 配置：`crontab -l`
2. 检查日志：`tail /tmp/gh_scheduler.log`
3. 检查 GH_TOKEN 环境变量
4. 手动测试：`python3 ~/task_scheduler.py --verbose --once`

### Agent 不执行任务
1. 检查任务文件是否存在：`ls /tmp/gh_tasks/{agent}/`
2. 检查任务状态是否为 pending
3. 检查 Agent HEARTBEAT 是否配置正确
4. 查看 Agent 日志

### GitHub API 错误
- 检查 GH_TOKEN 权限（需要 `project` 和 `repo` 权限）
- 检查项目 ID 和字段 ID 是否正确

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `task_scheduler_v2.py` | 主调度器（零Token） |
| `monitor_scheduler.py` | 运维监控脚本 |
| `README.md` | 本文档 |
| `/tmp/gh_tasks/{agent}/` | 任务文件目录 |
| `/tmp/gh_scheduler.log` | 调度器日志 |

---

## 更新日志

### v2.0 (2026-04-22)
- ✅ 改为任务文件方式，零 Token 消耗
- ✅ 移除 CLI 调用，避免 gateway 重复启动
- ✅ 简化架构，提高可靠性
- ✅ Agent HEARTBEAT 检查本地文件

### v1.0 (已废弃)
- ❌ 使用 CLI 调用，导致大量 gateway 进程
- ❌ 内存耗尽问题

---

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                      GitHub Projects                         │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐       │
│  │  Task 1 │  │  Task 2 │  │  Task 3 │  │  Task 4 │       │
│  │ Status  │  │ Status  │  │ Status  │  │ Status  │       │
│  │ Agent   │  │ Agent   │  │ Agent   │  │ Agent   │       │
│  │ Start   │  │ Start   │  │ Start   │  │ Start   │       │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘       │
└───────┼────────────┼────────────┼────────────┼────────────┘
        │            │            │            │
        └────────────┴────────────┴────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    系统 Cron (每分钟)                        │
│                          │                                  │
│                          ▼                                  │
│              ┌──────────────────────┐                      │
│              │   调度器 (Python)      │                      │
│              │   - 零Token消耗       │                      │
│              │   - 轮询GitHub API    │                      │
│              │   - 创建任务文件      │                      │
│              └──────────────────────┘                      │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    /tmp/gh_tasks/                          │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐          │
│  │ marketing/  │ │ content/    │ │ dev/        │          │
│  │ ├──task1.json│ │ ├──task2.json│ │ ├──task3.json│          │
│  │ └──task2.json│ │ └──task4.json│ │              │          │
│  └─────────────┘ └─────────────┘ └─────────────┘          │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Agent HEARTBEAT                           │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐          │
│  │  marketing  │ │   content   │ │     dev     │          │
│  │  检查文件   │ │   检查文件   │ │   检查文件   │          │
│  │  (零Token)  │ │  (零Token)  │ │  (零Token)  │          │
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘          │
│         │               │               │                  │
│         └───────────────┴───────────────┘                  │
│                         │                                  │
│                         ▼                                  │
│              ┌──────────────────────┐                      │
│              │   有任务?            │                      │
│              │   - 是: 执行(消耗Token)│                      │
│              │   - 否: HEARTBEAT_OK │                      │
│              └──────────────────────┘                      │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    更新 GitHub Projects                    │
│                    Status → Done                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 贡献

欢迎提交 Issue 和 PR！

## 许可证

MIT License