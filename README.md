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

# 添加以下行（每分钟执行一次，需设置 GH_TOKEN）
* * * * * export GH_TOKEN="ghp_your_github_token_here"; /usr/bin/python3 /Users/jiashaoshan/task_scheduler.py --once >> /tmp/gh_scheduler.log 2>&1
```

**步骤3：配置主 Agent HEARTBEAT**

主 Agent（main）负责统一检查所有任务文件并分发给对应 Agent。

**核心机制：**
- OpenClaw Cron 定时发送 message 给主 Agent
- message 中包含 Python 代码，Agent 执行后返回结果
- `sessions_spawn` 是 OpenClaw 内置函数，用于启动子 Agent

**代码逻辑：**
```python
import json
from pathlib import Path
from sessions_spawn import sessions_spawn
from datetime import datetime

def check_github_project_tasks():
    """检查 GitHub Projects 任务文件并分发"""
    tasks_dir = Path("/tmp/gh_tasks")
    triggered = []
    
    if not tasks_dir.exists():
        return None
    
    for agent_dir in tasks_dir.iterdir():
        if not agent_dir.is_dir() or agent_dir.name == "archive":
            continue
        
        agent_name = agent_dir.name
        
        for task_file in agent_dir.glob("*.json"):
            try:
                with open(task_file) as f:
                    task = json.load(f)
                
                if task.get("status") != "pending":
                    continue
                
                # 标记为 processing
                task["status"] = "processing"
                task["started_at"] = datetime.now().isoformat()
                with open(task_file, 'w') as f:
                    json.dump(task, f)
                
                # 启动对应 Agent 执行任务
                sessions_spawn({
                    "task": f"执行 GitHub Projects 任务: {task['title']}",
                    "runtime": "subagent",
                    "label": f"{agent_name}-github-task",
                    "mode": "run"
                })
                
                triggered.append({"agent": agent_name, "title": task['title']})
            except Exception as e:
                print(f"处理失败: {e}")
    
    return triggered

tasks = check_github_project_tasks()
if tasks:
    return f"【任务调度】已分发 {len(tasks)} 个任务"
else:
    return "HEARTBEAT_OK"
```

**注意：**
- 只有主 Agent 配置 HEARTBEAT，子 Agent 不配置
- 代码在 Step 4 的 OpenClaw Cron 任务中配置

### 4. 配置 OpenClaw Cron 定时任务

OpenClaw 通过 `~/.openclaw/cron/jobs.json` 管理定时任务。需要将 Python 代码直接嵌入任务的 `message` 中。

**方法：使用 Python 脚本添加**

```python
import json
import uuid
import time

# 读取现有 jobs
with open('/Users/jiashaoshan/.openclaw/cron/jobs.json', 'r') as f:
    data = json.load(f)

# 代码直接嵌入 message
code_message = '''执行 GitHub Projects 任务调度：

```python
import json
from pathlib import Path
from sessions_spawn import sessions_spawn
from datetime import datetime

def check_github_project_tasks():
    tasks_dir = Path("/tmp/gh_tasks")
    triggered = []
    
    if not tasks_dir.exists():
        return None
    
    for agent_dir in tasks_dir.iterdir():
        if not agent_dir.is_dir() or agent_dir.name == "archive":
            continue
        
        agent_name = agent_dir.name
        
        for task_file in agent_dir.glob("*.json"):
            try:
                with open(task_file) as f:
                    task = json.load(f)
                
                if task.get("status") != "pending":
                    continue
                
                task["status"] = "processing"
                task["started_at"] = datetime.now().isoformat()
                with open(task_file, 'w') as f:
                    json.dump(task, f)
                
                sessions_spawn({
                    "task": f"执行 GitHub Projects 任务: {task['title']}",
                    "runtime": "subagent",
                    "label": f"{agent_name}-github-task",
                    "mode": "run"
                })
                
                triggered.append({"agent": agent_name, "title": task['title']})
            except Exception as e:
                print(f"处理失败: {e}")
    
    return triggered

tasks = check_github_project_tasks()
if tasks:
    return f"【任务调度】已分发 {len(tasks)} 个任务"
else:
    return "HEARTBEAT_OK"
```

请执行上述代码。'''

# 创建新的 GitHub Projects 任务调度 job
new_job = {
    "id": str(uuid.uuid4()),
    "agentId": "main",
    "sessionKey": "agent:main:main",
    "name": "GitHub Projects 任务调度",
    "enabled": True,
    "createdAtMs": int(time.time() * 1000),
    "updatedAtMs": int(time.time() * 1000),
    "schedule": {
        "kind": "cron",
        "expr": "* * * * *",  # 每分钟执行
        "tz": "Asia/Shanghai"
    },
    "sessionTarget": "isolated",
    "wakeMode": "now",
    "payload": {
        "kind": "agentTurn",
        "message": code_message,
        "timeoutSeconds": 60
    },
    "delivery": {
        "mode": "none"  # 静默执行
    },
    "state": {
        "nextRunAtMs": 0,
        "lastRunAtMs": 0,
        "consecutiveErrors": 0
    }
}

# 添加到 jobs 列表
data['jobs'].append(new_job)

# 写回文件
with open('/Users/jiashaoshan/.openclaw/cron/jobs.json', 'w') as f:
    json.dump(data, f, indent=2)

print(f"已添加定时任务: {new_job['id']}")
print(f"任务名称: {new_job['name']}")
print(f"执行周期: {new_job['schedule']['expr']} (每分钟)")
```

**关键说明：**
- 代码直接嵌入 `payload.message`，Agent 收到后执行
- `sessions_spawn` 是 OpenClaw 内置函数，在 Agent 环境中可用
- 不需要外部脚本，避免模块导入问题

**验证定时任务：**

```bash
# 查看所有定时任务
cat ~/.openclaw/cron/jobs.json | python3 -c "import json,sys; data=json.load(sys.stdin); [print(f'{j[\"name\"]}: {j[\"schedule\"][\"expr\"]} - enabled:{j[\"enabled\"]}') for j in data['jobs']]"
```

### 5. 任务执行流程

```
创建任务(Status=Todo, Start date=今天)
    ↓ 调度器每分钟检查
到达开始时间 → 创建任务文件 /tmp/gh_tasks/{agent}/task.json
    ↓ 更新GitHub
Status → In progress
    ↓ 主 Agent HEARTBEAT检查
发现任务 → 启动对应 Agent 子进程
    ↓ Agent 执行
完成任务 → 更新 GitHub 状态 → "Done"
    ↓ 归档
任务文件移动到 /tmp/gh_tasks/{agent}/archive/
```

**Agent 执行完成后更新状态：**

```python
import subprocess

# Agent 执行完成后调用，更新 GitHub 状态
def update_github_status(item_id: str, success: bool = True):
    scheduler_path = "~/.openclaw/workspace/skills/github-projects/task_scheduler_v2.py"
    action = "--complete" if success else "--fail"
    subprocess.run([
        "python3", scheduler_path, action, item_id, "--agent", "marketing"
    ])
```

---

## 子 Agent 任务执行规范

每个子 Agent 的 `SKILLS.md` 必须包含以下规范：

### 1. 任务类型判断

```markdown
### 任务类型判断

执行任务前，先判断任务类型：

**GitHub Projects 任务**（任务来源: GitHub Projects）：
- 任务ID格式：`PVTI_xxx`
- **必须**自己更新GitHub状态

**直接对话派发任务**（任务来源: 直接对话派发）：
- 任务ID格式：普通字符串或对话ID
- **不需要**更新GitHub状态
- 直接群里汇报即可
```

### 2. GitHub Projects 任务状态自更新

```markdown
### GitHub Projects 任务状态自更新

当执行 GitHub Projects 自动任务时，子Agent必须自己更新任务状态：

**执行成功时**：
```python
import subprocess
# 标记任务完成
subprocess.run([
    "python3", 
    "~/.openclaw/workspace/skills/github-projects/task_scheduler_v2.py",
    "--complete", 
    "任务ID"  # 从主Agent派发的任务描述中获取
])
```

**执行失败时**：
```python
import subprocess
# 标记任务失败
subprocess.run([
    "python3",
    "~/.openclaw/workspace/skills/github-projects/task_scheduler_v2.py", 
    "--fail",
    "任务ID:失败原因"
])
```

**重要**：
- 先判断任务类型（看"任务来源"字段）
- 只有GitHub Projects任务需要更新状态
- 直接对话任务只需群里汇报
- 完成后立即处理，不要等待主Agent
```

### 3. 群内发言规则

```markdown
### 群内发言规则

当需要在AI智能团队群汇报时，必须使用自己的飞书Bot账号：

**调用方式**：
```javascript
message({
  accountId: "agent_name",  // 必须指定：如 dev, marketing 等
  action: "send",
  channel: "feishu",
  target: "oc_1d05adec7a7ee7b58bf89b9ecc718378",
  message: "【Agent名称】汇报内容..."
})
```

**关键要求**：
- 必须指定 accountId 为自己的 agent ID
- 消息开头标注身份【Agent名称】
- 先更新GitHub状态，再发群消息
- 同时返回完整结果给主Agent
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
python3 ~/task_scheduler_v2.py --verbose --once
```

### 手动标记任务完成
```bash
# Agent执行完成后调用
python3 ~/task_scheduler_v2.py --complete PVTI_xxx --agent marketing
```

---

## 故障排查

### 调度器不执行
1. 检查 crontab 配置：`crontab -l`
2. 检查日志：`tail /tmp/gh_scheduler.log`
3. 检查 GH_TOKEN 环境变量
4. 手动测试：`python3 ~/task_scheduler_v2.py --verbose --once`

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
| `AGENTS.md` | 主 Agent 配置（含 HEARTBEAT 逻辑） |
| `HEARTBEAT.md` | OpenClaw HEARTBEAT 配置 |
| `README.md` | 本文档 |
| `ai-team/*/SKILLS.md` | 各 Agent 技能路由配置 |
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
│                    主 Agent HEARTBEAT                        │
│                    (main - 统一调度)                         │
│                          │                                  │
│                          ▼                                  │
│              ┌──────────────────────┐                      │
│              │   检查所有任务文件    │                      │
│              │   /tmp/gh_tasks/*    │                      │
│              │   (零Token)          │                      │
│              └──────────┬───────────┘                      │
│                         │                                  │
│                         ▼                                  │
│              ┌──────────────────────┐                      │
│              │   有任务?            │                      │
│              │   - 是: 分发到对应Agent │                   │
│              │   - 否: HEARTBEAT_OK │                      │
│              └──────────┬───────────┘                      │
│                         │                                  │
│         ┌───────────────┼───────────────┐                  │
│         ▼               ▼               ▼                  │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐          │
│  │  marketing  │ │   content   │ │     dev     │          │
│  │  执行任务   │ │   执行任务   │ │   执行任务   │          │
│  │  (消耗Token)│ │  (消耗Token)│ │  (消耗Token)│          │
│  └─────────────┘ └─────────────┘ └─────────────┘          │
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