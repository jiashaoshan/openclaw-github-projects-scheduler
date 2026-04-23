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

# GitHub Token（必填）
export GH_TOKEN="ghp_your_github_token_here"

# GitHub Projects ID（可选，默认使用配置）
export GH_PROJECT_ID="PVT_kwHOABOkaM4BVDrk"

# 飞书群ID（可选，默认使用配置）
export GH_FEISHU_CHAT_ID="oc_1d05adec7a7ee7b58bf89b9ecc718378"

# OpenClaw Gateway Token（可选，自动从 ~/.openclaw/openclaw.json 读取）
export OPENCLAW_GATEWAY_TOKEN=""
```

**配置文件：**
项目目录下的 `config.json` 文件：
```json
{
  "gh_token": "",
  "project_id": "PVT_kwHOABOkaM4BVDrk",
  "feishu_chat_id": "oc_1d05adec7a7ee7b58bf89b9ecc718378",
  "ws_url": "ws://127.0.0.1:18789"
}
```

**配置优先级：** 环境变量 > 配置文件(config.json) > 代码默认值

### 2. 安装调度器

**步骤1：复制调度器脚本**
```bash
cp ~/.openclaw/workspace/skills/github-projects/github_scheduler_ws.py ~/github_scheduler.py
chmod +x ~/github_scheduler.py
```

**步骤2：配置调度器**

方式A - 使用环境变量（推荐用于敏感信息）：
```bash
# 添加到 ~/.zshrc 或 ~/.bash_profile

# GitHub Token（必填）
export GH_TOKEN="ghp_your_github_token_here"

# GitHub Projects ID（可选，默认使用配置）
export GH_PROJECT_ID="PVT_kwHOABOkaM4BVDrk"

# 飞书群ID（可选，默认使用配置）
export GH_FEISHU_CHAT_ID="oc_1d05adec7a7ee7b58bf89b9ecc718378xxxxxxxxxxxxx"

# OpenClaw Gateway Token（可选，自动从 ~/.openclaw/openclaw.json 读取）
export OPENCLAW_GATEWAY_TOKEN=""
```

方式B - 使用配置文件（推荐用于固定配置）：
```bash
# 编辑配置文件
vim ~/.openclaw/github-projects-config.json
```

配置文件示例：
```json
{
  "gh_token": "ghp_your_github_token_here",
  "project_id": "PVT_kwHOABOkaM4BVDrk",
  "feishu_chat_id": "oc_1d05adec7a7ee7b58bf89b9ecc718378xxxxxxxxxxxxx",
  "ws_url": "ws://127.0.0.1:18789"
}
```

**步骤3：配置系统 crontab**

```bash
# 编辑 crontab
crontab -e

# 添加以下行（每分钟执行一次，需设置 GH_TOKEN）
# ⚠️ 注意1：必须使用安装了 websockets 的 Python 完整路径
# ⚠️ 注意2：环境变量格式为 VAR=value command（不要用 export VAR; command）
* * * * * GH_TOKEN="ghp_your_github_token_here" /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 /Users/jiashaoshan/github_scheduler.py --once >> /tmp/gh_scheduler_ws.log 2>&1
```

**⚠️ Python 路径说明：**
- cron 的 PATH 和 shell 不同，必须指定完整 Python 路径
- 使用 `which python3` 查看你的 Python 路径
- 确保该 Python 已安装 websockets：`python3 -c "import websockets; print('OK')"`
- 常见路径示例：
  - macOS 系统 Python: `/usr/bin/python3`（可能没有 websockets）
  - Homebrew Python: `/usr/local/bin/python3`
  - pyenv Python: `/Users/xxx/.pyenv/shims/python3`
  - Framework Python: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3`

**⚠️ 环境变量格式：**
- ❌ 错误：`export GH_TOKEN="xxx"; command`（变量不会传递给 command）
- ✅ 正确：`GH_TOKEN="xxx" command`（变量正确传递给 command）

**步骤4：测试 WebSocket 连接**
```bash
# 测试 OpenClaw Gateway 连接
python3 github_scheduler_ws.py --test-connection --verbose

# 手动运行一次调度器
python3 github_scheduler_ws.py --once --verbose
```

### 3. 创建任务

#### 方式A：使用命令行工具（推荐）

使用 `create_task.py` 脚本快速创建任务：

```bash
# 创建默认任务（市场营销-热点新闻）
python3 create_task.py

# 创建指定 Agent 的任务
python3 create_task.py --agent marketing
python3 create_task.py --agent dev --title "【开发】开发新功能"

# 创建带自定义描述的任务
python3 create_task.py --agent content --title "【内容创作】小红书文案" --desc "详细描述..."

# 指定开始时间（默认今天）
python3 create_task.py --start-date 2026-04-24
```

**参数说明：**
- `--agent`: 指定 Agent (marketing/content/dev/consultant/finance/operations/ops)
- `--title`: 任务标题（默认: 【agent】获取最新的热点新闻）
- `--desc`: 任务描述（默认使用 Agent 模板）
- `--start-date`: 开始时间 YYYY-MM-DD（默认: 今天）

**环境变量：**
```bash
export GH_TOKEN="ghp_your_token"  # GitHub Token（必填）
```

### 方式B：手动在 GitHub Projects 中创建

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
   ├── WebSocket连接到 OpenClaw Gateway
   └── 【群汇报】发送「调度器启动」通知（有任务时）
            ↓
3. 直接调用 Agent
   ├── 调用 sessions.create(agentId="xxx", message="任务内容")
   ├── 实时接收Agent流式回复
   ├── 等待任务执行完成
   ├── **Agent 添加任务执行评论**（必须）
   └── Agent 自行更新 GitHub 状态 → "Done/Failed"
            ↓
4. 执行完成
   ├── 【群汇报】发送「任务调度完成」汇总
   ├── 成功数/失败数统计
   └── 任务清单展示
            ↓
5. 清理
   └── 关闭WebSocket连接

**Agent 执行规范：**
1. **添加评论** → 记录执行摘要、关键结果、问题
2. **更新状态** → Done 或 Failed
3. **群里汇报** → 使用自己的飞书Bot
4. **返回结果** → 给主Agent
```

**汇报规则：**
- ✅ 有任务时：发送「调度器启动」+「任务调度完成」
- ✅ 无任务时：静默执行，不发送消息
- ✅ Agent 执行完成后：各自在群里汇报结果

---

## 核心组件

| 文件 | 功能 | 调用方式 |
|------|------|----------|
| `github_scheduler_ws.py` | 主调度器，WebSocket直接调用 | 系统 crontab 每分钟 |
| `test_openclaw_gateway_ws.py` | WebSocket连接测试脚本 | 手动测试 |
| `task_scheduler_v2.py` | v2旧版调度器（已弃用） | 参考 |
| `monitor_scheduler.py` | 调度器监控脚本 | 每30分钟检查 |
| `deploy_v3.sh` | v3部署脚本 | 一键部署 |
| `AGENTS.md` | 主 Agent 配置（含任务路由） | 参考 |
| `ai-team/*/SKILLS.md` | 各 Agent 技能路由配置 | 任务执行规范 |

---

## 各 Agent 任务行为规范

每个 Agent 的 `SKILLS.md` 文件必须包含「任务执行规范」章节，定义任务的执行和汇报规则。

### 任务执行规范（必须包含）

在每个 Agent 的 `~/.openclaw/workspace/ai-team/{agent}/SKILLS.md` 中添加：


## 任务执行规范

### 任务类型判断

执行任务前，先判断任务类型：

**直接对话派发任务**（任务来源: 直接对话派发）：
- 任务ID格式：普通字符串或对话ID
- **不需要** 执行完任务后，更新GitHub状态
- **不需要** 执行完任务后，更新GitHub评论
- 直接群里汇报、返回结果即可

**GitHub Projects 任务**（任务来源: GitHub Projects）：
- 任务ID格式：`PVTI_xxx`
- **必须** 执行任务前，向团队飞书群里汇报（用自己的飞书bot账号）
- **必须** 执行完任务后，更新GitHub任务状态
- **必须** 执行完任务后，添加GitHub任务评论
- **必须** 执行完任务后，向团队飞书群里汇报结果（用自己的飞书bot账号）


### GitHub Projects 任务执行流程

当执行 GitHub Projects 自动任务时，子Agent在任务执行完成后，必须按以下顺序执行：

**第1步：执行任务前，向团队飞书群里汇报（用自己的飞书bot账号）**

按‘群内发言规则’调用方式向飞书群汇报，汇报内容模版：

```
【你的Agent名称】接受任务【任务ID】开始执行，时间【2026-XX-XX XX:XX:XX】>>>>>>>>>>>>
```

**第2步：任务执行**

当前Agent执行任务

**第3步：更新任务状态为 Done（必须，防止重复执行）**

先更新状态，防止调度器重复触发：

```python
import subprocess
# 标记任务完成
subprocess.run([
    "python3",
    "~/.openclaw/workspace/skills/github-projects/task_scheduler_v2.py",
    "--complete",
    "任务ID",  # 从任务描述中获取
    "--agent",
    "你的agent名称"  # dev/content/marketing等
])
```

**执行失败时**：
```python
import subprocess
# 标记任务失败（会自动添加失败评论）
subprocess.run([
    "python3",
    "~/.openclaw/workspace/skills/github-projects/task_scheduler_v2.py",
    "--fail",
    "任务ID:失败原因",
    "--agent",
    "你的agent名称"
])
```

**第4步：添加任务执行评论**

状态更新后，添加评论记录执行情况：

```python
import subprocess
# 添加任务执行评论
subprocess.run([
    "python3",
    "~/.openclaw/workspace/skills/github-projects/task_scheduler_v2.py",
    "--comment",
    "任务ID",  # 从任务描述中获取
    "--body",
    """## ✅ 任务执行完成

**执行Agent**: [你的Agent名称]
**执行时间**: 2026-XX-XX XX:XX
**执行结果**: 成功

**执行摘要**
- 完成的任务：[简要描述]
- 关键结果：[关键产出]
- 遇到的问题：[如有]

**详细说明**
[详细描述执行过程和结果]
"""])
```
**第5步：执行结束，向团队飞书群里汇报结果（用自己的飞书bot账号）**

按‘群内发言规则’调用方式向飞书群汇报，汇报内容模版：

```
**执行Agent**: [你的Agent名称]
**执行时间**: 2026-XX-XX XX:XX:XX
**执行结果**: 成功!
**执行摘要**
- 完成的任务：[简要描述]
- 关键结果：[关键产出]
- 遇到的问题：[如有]
```

**GitHub Projects 任务重要顺序**：
1. **群里汇报** → 汇报开始（用自己的飞书bot）
2. **先更新状态** → `--complete` 或 `--fail`（防止重复执行）
3. **再添加评论** → `--comment` + `--body`
4. **群里汇报** → 汇报执行结果（使用自己飞书Bot）
5. **返回结果** → 给主Agent

**非GitHub Projects 任务重要顺序**：
1. **群里汇报** → 使用自己飞书Bot
2. **返回结果** → 给主Agent

### 群内发言规则

当需要在AI智能团队群汇报时，必须使用自己的飞书Bot账号：

**调用方式**：
```javascript
message({
  accountId: "你的agent名称",  // 必须指定：dev/content/marketing等
  action: "send",
  channel: "feishu",
  target: "oc_1d05adec7a7ee7b58bf89b9ecc718378",  // 群ID
  message: "【你的身份】汇报内容..."
})
```

**关键要求**：
- 必须指定 accountId 为自己的 agent ID
- 消息开头标注身份【开发】/【内容创作】等
- 先更新GitHub状态，再发群消息
- 同时返回完整结果给主Agent


---

## 参考实现

查看各 Agent 的 SKILLS.md 文件：
- `ai-team/dev/SKILLS.md` - 开发 Agent 规范
- `ai-team/content/SKILLS.md` - 内容创作 Agent 规范
- `ai-team/marketing/SKILLS.md` - 市场营销 Agent 规范
- `ai-team/consultant/SKILLS.md` - 咨询顾问 Agent 规范
- `ai-team/finance/SKILLS.md` - 财务 Agent 规范
- `ai-team/operations/SKILLS.md` - 客户运营 Agent 规范
- `ai-team/ops/SKILLS.md` - 运维 Agent 规范

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

### v3.1 (2026-04-23)
- ✅ 增加调度器群汇报功能
- ✅ 有任务时发送「调度器启动」和「任务调度完成」通知
- ✅ 无任务时静默执行
- ✅ 各 Agent 执行完成后在群里分别汇报

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
├── github_scheduler_ws.py    # v3主调度器（WebSocket版，含群汇报）
├── test_openclaw_gateway_ws.py  # WebSocket测试脚本
├── task_scheduler_v2.py      # v2旧版调度器（已弃用）
├── monitor_scheduler.py      # 调度器监控
├── deploy_v3.sh              # v3部署脚本
├── README.md                 # 完整文档
├── SKILL.md                  # OpenClaw技能文件
├── MIGRATION_v2_to_v3.md     # v2到v3迁移指南
└── ai-team/                  # Agent技能配置（含任务行为规范）
    ├── dev/SKILLS.md
    ├── content/SKILLS.md
    ├── marketing/SKILLS.md
    ├── consultant/SKILLS.md
    ├── finance/SKILLS.md
    ├── operations/SKILLS.md
    └── ops/SKILLS.md
```
---

最终修改@20260423

## 许可证

MIT License

