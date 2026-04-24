#!/usr/bin/env python3
"""
GitHub Projects WebSocket 调度器 v3

新架构（直接WebSocket调用）：
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

使用方法：
    # 系统cron定时调用（每分钟）
    * * * * * /usr/bin/python3 /path/to/github_scheduler_ws.py --once >> /tmp/gh_scheduler_ws.log 2>&1
    
    # 手动测试
    python3 github_scheduler_ws.py --verbose --once
    
    # 测试WebSocket连接
    python3 github_scheduler_ws.py --test-connection
    
    # Agent 调用（标记任务完成）
    python3 github_scheduler_ws.py --complete ITEM_ID
    
    # Agent 调用（标记任务失败）
    python3 github_scheduler_ws.py --fail ITEM_ID
    
    # Agent 调用（添加评论）
    python3 github_scheduler_ws.py --comment ITEM_ID --body "评论内容"
"""

import asyncio
import json
import os
import sys
import time
import argparse
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
import uuid

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
except ImportError:
    print("❌ 缺少 websockets，请先安装: pip install websockets")
    sys.exit(1)

# ============ 配置加载 ============
# 配置文件路径（项目目录）
CONFIG_FILE = Path(__file__).parent / "config.json"

def load_config():
    """加载配置，只从配置文件读取"""
    if not CONFIG_FILE.exists():
        print(f"❌ 配置文件不存在: {CONFIG_FILE}")
        sys.exit(1)
    
    with open(CONFIG_FILE) as f:
        config = json.load(f)
    print(f"✅ 已加载配置文件: {CONFIG_FILE}")
    return config

# 加载配置
CONFIG = load_config()

# ============ 配置项 ============
# 优先从环境变量读取 GH_TOKEN，否则使用配置文件
GH_TOKEN = os.environ.get("GH_TOKEN", CONFIG.get("gh_token", ""))
PROJECT_ID = CONFIG["project_id"]
FEISHU_CHAT_ID = CONFIG["feishu_chat_id"]

# 以下字段 ID 和选项 ID 将在运行时自动获取
STATUS_FIELD_ID = None
AGENT_FIELD_ID = None
START_DATE_FIELD_ID = None

# 状态选项 ID（运行时自动填充）
STATUS_TODO = None
STATUS_IN_PROGRESS = None
STATUS_DONE = None
STATUS_FAILED = None

# Agent 选项映射：选项名称 -> 选项 ID（运行时自动填充）
AGENT_OPTIONS = {}

# 支持的 Agent 名称列表
AGENT_NAMES = ["marketing", "content", "dev", "consultant", "finance", "operations", "ops", "hermes", "main"]

# WebSocket配置
DEFAULT_WS_URL = CONFIG["ws_url"]
DEFAULT_GATEWAY_TOKEN = CONFIG["gateway_token"]

VERBOSE = False

# 锁文件路径（防止重复运行）
LOCK_FILE = Path("/tmp/gh_scheduler.lock")

# 最大并发任务数
MAX_CONCURRENT_TASKS = 3

# ============ 日志 ============
def log(msg: str, force: bool = False):
    if VERBOSE or force:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {msg}", flush=True)


# ============ GitHub API ============

def graphql_query(query: str, variables: Dict = None) -> Dict:
    """执行 GraphQL 查询"""
    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    
    try:
        resp = requests.post(
            "https://api.github.com/graphql",
            headers=headers,
            json=payload,
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            log(f"GraphQL错误: {data['errors']}")
            return {}
        return data.get("data", {})
    except Exception as e:
        log(f"请求失败: {e}")
        return {}


def resolve_project_fields():
    """
    自动获取项目的字段 ID 和选项 ID（根据字段名称），
    取代硬编码的字段 ID 配置。
    设置全局变量：STATUS_FIELD_ID, AGENT_FIELD_ID, START_DATE_FIELD_ID,
    STATUS_TODO, STATUS_IN_PROGRESS, STATUS_DONE, STATUS_FAILED, AGENT_OPTIONS
    """
    global STATUS_FIELD_ID, AGENT_FIELD_ID, START_DATE_FIELD_ID
    global STATUS_TODO, STATUS_IN_PROGRESS, STATUS_DONE, STATUS_FAILED
    global AGENT_OPTIONS
    
    # 首先尝试从配置文件加载硬编码值
    STATUS_FIELD_ID = CONFIG.get("status_field_id")
    AGENT_FIELD_ID = CONFIG.get("agent_field_id")
    START_DATE_FIELD_ID = CONFIG.get("start_date_field_id")
    
    query = """
    query($projectId: ID!) {
        node(id: $projectId) {
            ... on ProjectV2 {
                fields(first: 20) {
                    nodes {
                        __typename
                        ... on ProjectV2FieldCommon {
                            name
                            id
                        }
                        ... on ProjectV2SingleSelectField {
                            name
                            id
                            options {
                                id
                                name
                            }
                        }
                    }
                }
            }
        }
    }
    """
    
    data = graphql_query(query, {"projectId": PROJECT_ID})
    if not data:
        log("⚠️ 无法从API获取项目字段信息，使用配置文件中的硬编码值", force=True)
        # 使用硬编码的选项ID（这些需要手动从GitHub Projects界面获取）
        STATUS_TODO = CONFIG.get("status_todo_id", "f0fd8bec")
        STATUS_IN_PROGRESS = CONFIG.get("status_in_progress_id", "0fded4e8")
        STATUS_DONE = CONFIG.get("status_done_id", "98236657")
        STATUS_FAILED = CONFIG.get("status_failed_id", "7c1d073d")
        # Agent选项映射需要从配置或环境变量获取
        AGENT_OPTIONS = CONFIG.get("agent_options", {})
        return True  # 使用硬编码值继续执行
    
    fields = data.get("node", {}).get("fields", {}).get("nodes", [])
    for field in fields:
        field_name = field.get("name", "")
        
        # 找到 Status 字段及其选项
        if field_name == "Status":
            STATUS_FIELD_ID = field.get("id")
            for opt in field.get("options", []):
                opt_name = opt.get("name", "")
                if opt_name == "Todo":
                    STATUS_TODO = opt.get("id")
                elif opt_name == "In progress":
                    STATUS_IN_PROGRESS = opt.get("id")
                elif opt_name == "Done":
                    STATUS_DONE = opt.get("id")
                elif opt_name == "Failed":
                    STATUS_FAILED = opt.get("id")
        
        # 找到 Agent 字段及其选项
        elif field_name == "Agent":
            AGENT_FIELD_ID = field.get("id")
            for opt in field.get("options", []):
                opt_name = opt.get("name", "")
                if opt_name in AGENT_NAMES:
                    AGENT_OPTIONS[opt_name] = opt.get("id")
        
        # 找到 Start date 字段
        elif field_name == "Start date":
            START_DATE_FIELD_ID = field.get("id")
    
    # 验证是否全部获取成功
    missing = []
    if not STATUS_FIELD_ID or not STATUS_TODO: missing.append("Status字段")
    if not AGENT_FIELD_ID or not AGENT_OPTIONS: missing.append("Agent字段")
    if not START_DATE_FIELD_ID: missing.append("Start date字段")
    
    if missing:
        log(f"⚠️ 项目字段解析不完整，缺少: {', '.join(missing)}", force=True)
        # 尝试从配置文件加载选项ID
        STATUS_TODO = CONFIG.get("status_todo_id")
        STATUS_IN_PROGRESS = CONFIG.get("status_in_progress_id")
        STATUS_DONE = CONFIG.get("status_done_id")
        STATUS_FAILED = CONFIG.get("status_failed_id")
        AGENT_OPTIONS = CONFIG.get("agent_options", {})
        
        if STATUS_TODO and STATUS_IN_PROGRESS and STATUS_DONE:
            log(f"✅ 已从配置文件加载选项 ID", force=True)
            return True
        
        log("❌ 无法获取项目选项 ID，请执行以下步骤之一：", force=True)
        log("   方案1: gh auth refresh -s read:project -s project", force=True)
        log("   方案2: 访问 https://github.com/settings/tokens 创建带 read:project 的 Token", force=True)
        log("   方案3: 手动在 config.json 中添加 status_todo_id, status_in_progress_id, status_done_id", force=True)
        return False
    
    log(f"✅ 已自动获取项目字段和选项 ID：Status={STATUS_FIELD_ID[:12]}... Agent选项={len(AGENT_OPTIONS)}个")
    return True


def get_project_items() -> List[Dict]:
    """获取项目中的所有任务"""
    query = """
    query($projectId: ID!) {
        node(id: $projectId) {
            ... on ProjectV2 {
                items(first: 100) {
                    nodes {
                        id
                        content {
                            ... on Issue {
                                title
                                body
                                number
                                state
                            }
                            ... on DraftIssue {
                                title
                                body
                            }
                        }
                        fieldValues(first: 20) {
                            nodes {
                                ... on ProjectV2ItemFieldSingleSelectValue {
                                    field { ... on ProjectV2FieldCommon { name } }
                                    name
                                    optionId
                                }
                                ... on ProjectV2ItemFieldDateValue {
                                    field { ... on ProjectV2FieldCommon { name } }
                                    date
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    """
    
    data = graphql_query(query, {"projectId": PROJECT_ID})
    if not data:
        return []
    
    items = []
    for node in data.get("node", {}).get("items", {}).get("nodes", []):
        item_id = node.get("id")
        content = node.get("content", {})
        title = content.get("title", "")
        body = content.get("body", "")
        
        # 解析字段值
        status = None
        agent = None
        start_date = None
        
        for fv in node.get("fieldValues", {}).get("nodes", []):
            field_name = fv.get("field", {}).get("name", "")
            if field_name == "Status":
                status = fv.get("optionId")
            elif field_name == "Agent":
                agent = fv.get("optionId")
            elif field_name == "Start date":
                start_date = fv.get("date")
        
        items.append({
            "id": item_id,
            "title": title,
            "body": body,
            "status": status,
            "agent": agent,
            "start_date": start_date
        })
    
    return items


def update_item_status(item_id: str, status_option_id: str) -> bool:
    """更新任务状态"""
    if not STATUS_FIELD_ID:
        log("❌ STATUS_FIELD_ID 未设置")
        return False
    
    mutation = """
    mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
        updateProjectV2ItemFieldValue(
            input: {
                projectId: $projectId
                itemId: $itemId
                fieldId: $fieldId
                value: { singleSelectOptionId: $optionId }
            }
        ) {
            clientMutationId
        }
    }
    """
    
    result = graphql_query(mutation, {
        "projectId": PROJECT_ID,
        "itemId": item_id,
        "fieldId": STATUS_FIELD_ID,
        "optionId": status_option_id
    })
    
    if not result:
        log(f"⚠️ 状态更新API调用失败 (optionId={status_option_id})")
        return False
    if "errors" in result:
        log(f"⚠️ 状态更新GraphQL错误: {result['errors']}")
        return False
    return True


def get_agent_name_by_option_id(option_id: str) -> Optional[str]:
    """根据option ID获取Agent名称"""
    for name, oid in AGENT_OPTIONS.items():
        if oid == option_id:
            return name
    return None


# ============ Agent 命令行工具（供SKILLS.md调用） ============

def complete_task(item_id: str) -> bool:
    """标记任务为完成（供Agent调用）"""
    log(f"标记任务完成: {item_id}")
    if not resolve_project_fields():
        log("❌ 无法获取项目字段信息")
        return False
    return update_item_status(item_id, STATUS_DONE)


def fail_task(item_id: str) -> bool:
    """标记任务为失败（供Agent调用）"""
    log(f"标记任务失败: {item_id}")
    if not resolve_project_fields():
        log("❌ 无法获取项目字段信息")
        return False
    return update_item_status(item_id, STATUS_FAILED)


def add_task_comment(item_id: str, body: str) -> bool:
    """添加任务评论（供Agent调用）"""
    log(f"添加评论到任务: {item_id}")
    
    # 首先获取任务的 Issue/PR ID
    query = """
    query($itemId: ID!) {
        node(id: $itemId) {
            ... on ProjectV2Item {
                content {
                    ... on Issue { id number }
                    ... on PullRequest { id number }
                }
            }
        }
    }
    """
    
    result = graphql_query(query, {"itemId": item_id})
    if not result:
        log("❌ 无法获取任务内容ID")
        return False
    
    content = result.get("node", {}).get("content", {})
    issue_id = content.get("id") if content else None
    
    if not issue_id:
        log("❌ 任务没有关联的Issue/PR")
        return False
    
    # 添加评论
    mutation = """
    mutation($subjectId: ID!, $body: String!) {
        addComment(input: {subjectId: $subjectId, body: $body}) {
            commentEdge { node { id } }
        }
    }
    """
    
    result = graphql_query(mutation, {"subjectId": issue_id, "body": body})
    if result and "errors" not in result:
        log("✅ 评论添加成功")
        return True
    else:
        log(f"❌ 评论添加失败: {result.get('errors', 'Unknown error')}")
        return False


# ============ WebSocket Client ============

class OpenClawGatewayClient:
    """OpenClaw Gateway WebSocket 客户端"""
    
    def __init__(self, ws_url: str = None, token: str = None):
        self.ws_url = ws_url or DEFAULT_WS_URL
        self.token = token or DEFAULT_GATEWAY_TOKEN
        self.ws = None
        self.request_id = 0
        self.received_events = []
    
    async def connect(self) -> bool:
        """连接到 WebSocket Gateway 并完成握手"""
        try:
            self.ws = await websockets.connect(self.ws_url)
            log(f"✅ WebSocket已连接: {self.ws_url}")
            
            # 等待 connect.challenge 事件
            log(f"[WebSocket] 等待 connect.challenge...")
            t0 = time.time()
            while time.time() - t0 < 10:
                try:
                    raw = await asyncio.wait_for(self.ws.recv(), timeout=2)
                    evt = json.loads(raw)
                    if evt.get("event") == "connect.challenge":
                        log(f"[WebSocket] ✅ 收到 connect.challenge")
                        break
                    self.received_events.append(evt)
                except asyncio.TimeoutError:
                    continue
            else:
                log(f"[WebSocket] ❌ 等待 connect.challenge 超时")
                return False
            
            # 发送 connect 握手
            await self._send_connect()
            return True
        except Exception as e:
            log(f"❌ WebSocket连接失败: {e}")
            return False
    
    async def _send_connect(self):
        """发送 connect 握手请求"""
        self.request_id += 1
        connect_req_id = f"connect-{self.request_id}"
        frame = {
            "type": "req",
            "id": connect_req_id,
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {
                    "id": "gateway-client",
                    "version": "1.0.0",
                    "platform": "python",
                    "mode": "backend"
                },
                "auth": {
                    "token": self.token
                } if self.token else {},
                "role": "operator",
                "scopes": ["operator.admin"],
                "caps": []
            }
        }
        await self.ws.send(json.dumps(frame))
        log(f"[WebSocket] 发送 connect 握手...")
        
        # 等待 connect 响应
        t0 = time.time()
        while time.time() - t0 < 10:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=2)
                msg = json.loads(raw)
                if msg.get("id") == connect_req_id:
                    if msg.get("type") == "res":
                        log(f"[WebSocket] ✅ connect 握手成功")
                        return
                    elif msg.get("type") == "err":
                        log(f"[WebSocket] ❌ connect 握手失败: {msg}")
                        raise Exception(f"connect failed: {msg}")
                self.received_events.append(msg)
            except asyncio.TimeoutError:
                continue
        log(f"[WebSocket] ❌ connect 握手超时")
    
    async def close(self):
        """关闭连接"""
        if self.ws:
            await self.ws.close()
            log("WebSocket连接已关闭")
    
    async def request(self, method: str, params: Dict = None, timeout: int = 10) -> Dict:
        """发送请求并等待响应"""
        self.request_id += 1
        req_id = f"req-{self.request_id}"
        
        frame = {
            "type": "req",
            "id": req_id,
            "method": method,
            "params": params or {}
        }
        
        await self.ws.send(json.dumps(frame))
        
        # 等待响应
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=2)
                msg = json.loads(raw)
                
                # 检查是否是响应
                if msg.get("id") == req_id:
                    return msg
                # 否则存入事件列表
                self.received_events.append(msg)
            except asyncio.TimeoutError:
                continue
        
        return {"type": "timeout", "method": method}
    
    async def execute_agent_task(self, agent_id: str, task_title: str, 
                                  task_body: str, item_id: str, 
                                  timeout: int = 300) -> Dict:
        """
        执行Agent任务并等待完成
        
        发送的任务消息格式：
        {
            "github_task": {
                "item_id": "...",
                "title": "...",
                "body": "..."
            }
        }
        """
        # 构建任务消息（包含状态更新指令）
        task_message = f"""执行GitHub Projects任务

任务来源: GitHub Projects
任务ID: {item_id}
任务标题: {task_title}
任务描述: {task_body}

请按以下步骤执行：
1. 读取 ~/.openclaw/workspace/ai-team/{agent_id}/SKILLS.md
2. 根据任务描述找到匹配的技能路由
3. 按照SKILLS.md中「任务执行规范」-「GitHub Projects 任务执行流程」的按步骤顺序执行
4. 返回执行结果摘要

注意：
- 所有执行细节（汇报格式、命令参数、执行顺序）以SKILLS.md中的「任务执行规范」为准
- 完成后立即处理，不要等待主Agent
"""

        self.request_id += 1
        create_req_id = f"session-create-{self.request_id}"
        create_frame = {
            "type": "req",
            "id": create_req_id,
            "method": "sessions.create",
            "params": {
                "agentId": agent_id,
                "message": task_message
            }
        }
        
        log(f"发送任务到Agent [{agent_id}]: {task_title[:50]}...")
        await self.ws.send(json.dumps(create_frame))

        chunks = []
        session_key = None
        run_id = None
        t0 = time.time()
        first_chunk = None
        final_state = None

        while time.time() - t0 < timeout:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=2)
                msg = json.loads(raw)

                # 检查 sessions.create 响应
                if msg.get("id") == create_req_id:
                    if msg.get("type") == "res":
                        if msg.get("ok"):
                            payload = msg.get("payload", {})
                            session_key = payload.get("key")
                            run_id = payload.get("runId")
                            log(f"会话创建成功: {session_key[:40]}..." if session_key and len(session_key) > 40 else f"会话创建成功: {session_key}")
                        else:
                            error_detail = msg.get("error", {})
                            log(f"❌ 会话创建失败: {error_detail}")
                            return {"error": error_detail, "chunks": []}

                # 收集 agent 回复事件
                event_type = msg.get("event", "")
                payload = msg.get("payload", {})

                # chat 事件包含回复内容
                if event_type == "chat" and isinstance(payload, dict):
                    state = payload.get("state", "")
                    message = payload.get("message", {})
                    if isinstance(message, dict):
                        content_list = message.get("content", [])
                        if isinstance(content_list, list) and len(content_list) > 0:
                            text = content_list[0].get("text", "")
                            if text:
                                if first_chunk is None:
                                    first_chunk = time.time() - t0
                                    log(f"首字节延迟: {first_chunk:.2f}s")
                                chunks.append(text)
                    
                    final_state = state
                    # final/complete 状态表示流结束
                    if state in ("final", "complete"):
                        elapsed = time.time() - t0
                        log(f"✅ 任务执行完成 ({elapsed:.1f}s)")
                        return {
                            "session_key": session_key,
                            "run_id": run_id,
                            "chunks": chunks,
                            "state": state,
                            "elapsed": elapsed,
                            "first_chunk": first_chunk
                        }
                    # error 状态表示出错
                    elif state == "error":
                        elapsed = time.time() - t0
                        log(f"❌ 任务执行出错 ({elapsed:.1f}s)")
                        return {
                            "error": "execution_error",
                            "chunks": chunks,
                            "state": state,
                            "elapsed": elapsed
                        }
                    # cancelled 状态表示被取消
                    elif state == "cancelled":
                        elapsed = time.time() - t0
                        log(f"⚠️ 任务被取消 ({elapsed:.1f}s)")
                        return {
                            "error": "cancelled",
                            "chunks": chunks,
                            "state": state,
                            "elapsed": elapsed
                        }
                    
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                log(f"❌ 接收消息异常: {e}")
                return {"error": str(e), "chunks": chunks}

        # 超时
        elapsed = time.time() - t0
        log(f"⏱️ 任务执行超时 ({elapsed:.1f}s)")
        return {
            "error": "timeout",
            "chunks": chunks,
            "elapsed": elapsed
        }


# ============ 主调度逻辑 ============

async def _execute_single_task(client: OpenClawGatewayClient, task: Dict) -> Dict:
    """
    执行单个 Agent 任务（并行调用单元）
    每个任务使用独立的 WebSocket 连接，避免消息串扰。
    """
    item_id = task["item_id"]
    title = task["title"]
    body = task["body"]
    agent = task["agent"]
    
    log(f"\n[并行] 处理任务: [{agent}] {title[:50]}...")
    log(f"[并行] 任务详情: item_id={item_id[:30]}...")
    
    # 更新状态为 In progress
    log(f"[并行] 正在更新状态为 In progress...")
    if not update_item_status(item_id, STATUS_IN_PROGRESS):
        log(f"[并行] ❌ 更新状态失败，跳过任务: {title[:30]}...")
        return {"item_id": item_id, "success": False, "error": "update_status_failed"}
    log(f"[并行] ✅ 状态已更新为 In progress")
    
    try:
        log(f"[并行] 开始执行 Agent 任务...")
        result = await client.execute_agent_task(
            agent_id=agent,
            task_title=title,
            task_body=body,
            item_id=item_id,
            timeout=300
        )
        
        log(f"[并行] Agent 返回结果: {result.keys()}")
        
        if result.get("error"):
            error_msg = result.get("error")
            log(f"[并行] ❌ Agent执行失败: {error_msg}")
            log(f"[并行] 正在更新状态为 Failed...")
            update_item_status(item_id, STATUS_FAILED)
            log(f"[并行] ✅ 状态已更新为 Failed")
            return {"item_id": item_id, "success": False, "error": error_msg}
        else:
            reply = "".join(result.get("chunks", []))
            elapsed = result.get('elapsed', 0)
            log(f"[并行] ✅ [{agent}] 执行完成: {title[:50]}... ({elapsed:.1f}s)")
            log(f"[并行] 正在更新状态为 Done...")
            update_item_status(item_id, STATUS_DONE)
            log(f"[并行] ✅ 状态已更新为 Done")
            return {"item_id": item_id, "success": True, "reply": reply}
            
    except Exception as e:
        log(f"[并行] ❌ 执行异常: {e}")
        log(f"[并行] 正在回滚状态为 Todo...")
        update_item_status(item_id, STATUS_TODO)  # 回滚，等待下次重试
        log(f"[并行] ✅ 状态已回滚为 Todo")
        return {"item_id": item_id, "success": False, "error": str(e)}


async def _execute_task_with_own_ws(task: Dict) -> Dict:
    """
    为单个任务创建独立 WebSocket 连接并执行。
    这样多个任务可以真正并行，互不影响消息接收。
    """
    item_id = task["item_id"]
    title = task["title"][:30]
    
    log(f"\n[并行] ========== 开始处理任务: {title}... ==========")
    log(f"[并行] 创建 WebSocket 连接...")
    
    client = OpenClawGatewayClient()
    if not await client.connect():
        log(f"[并行] ❌ WebSocket连接失败: {title}...")
        log(f"[并行] 正在回滚状态为 Todo...")
        update_item_status(item_id, STATUS_TODO)  # 回滚
        log(f"[并行] ✅ 状态已回滚为 Todo")
        return {"item_id": item_id, "success": False, "error": "ws_connect_failed"}
    
    log(f"[并行] ✅ WebSocket连接成功")
    
    try:
        result = await _execute_single_task(client, task)
        log(f"[并行] ========== 任务处理完成: {title}... ==========")
        return result
    finally:
        log(f"[并行] 关闭 WebSocket 连接...")
        await client.close()
        log(f"[并行] ✅ WebSocket连接已关闭")


async def check_and_trigger_tasks():
    """检查并触发任务（调度器主逻辑 - 并行版本）"""
    
    # 锁文件检查：防止上一轮还没执行完，下一轮又开始了
    if LOCK_FILE.exists():
        log("⏳ 上一轮调度还在执行中，跳过本轮")
        return 0, 0
    
    # 创建锁文件（进程退出时清理由 finally 保证，但这里只设标志）
    LOCK_FILE.write_text(datetime.now().isoformat())
    
    try:
        return await _check_and_trigger_tasks_impl()
    finally:
        # 释放锁文件，无论成功/异常都清理
        try:
            LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass


async def _check_and_trigger_tasks_impl():
    """调度器内部实现（已加锁保护）"""
    log("\n" + "="*60)
    log("开始检查GitHub Projects任务...")
    
    # 首次运行时自动获取字段配置
    if STATUS_FIELD_ID is None:
        if not resolve_project_fields():
            log("❌ 无法获取项目字段信息，请检查 GH_TOKEN 和 project_id", force=True)
            return 0, 0
    
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log(f"[调度器] 今天日期: {today}")
    
    items = get_project_items()
    log(f"[调度器] 从 GitHub Projects 获取到 {len(items)} 个任务")
    
    # 先过滤出需要处理的任务
    pending_tasks = []
    skipped = {"not_todo": 0, "no_start_date": 0, "not_due": 0, "no_agent": 0}
    
    for item in items:
        item_id = item["id"]
        title = item["title"]
        status = item["status"]
        agent_option_id = item["agent"]
        start_date = item["start_date"]
        
        # 只处理 Todo 状态的任务
        if status != STATUS_TODO:
            skipped["not_todo"] += 1
            continue
        
        # 检查开始时间 - 必须有 start date 且已到期才执行
        if not start_date:
            log(f"⏳ 任务无开始时间，跳过: {title[:30]}...")
            skipped["no_start_date"] += 1
            continue
        if start_date > today:
            log(f"⏳ 任务未到期: {title[:30]}... (开始时间: {start_date})")
            skipped["not_due"] += 1
            continue
        
        # 获取Agent名称
        agent = get_agent_name_by_option_id(agent_option_id)
        if not agent:
            log(f"⚠️ 未知Agent: {agent_option_id}, 任务: {title[:30]}...")
            skipped["no_agent"] += 1
            continue
        
        pending_tasks.append({
            "item_id": item_id,
            "title": title,
            "body": item.get("body", ""),
            "agent": agent
        })
        log(f"[调度器] ✅ 任务符合条件: [{agent}] {title[:40]}... (start_date: {start_date})")
    
    log(f"[调度器] 任务筛选统计:")
    log(f"[调度器]   - 跳过（非Todo）: {skipped['not_todo']}")
    log(f"[调度器]   - 跳过（无开始时间）: {skipped['no_start_date']}")
    log(f"[调度器]   - 跳过（未到期）: {skipped['not_due']}")
    log(f"[调度器]   - 跳过（未知Agent）: {skipped['no_agent']}")
    log(f"[调度器]   - 符合条件: {len(pending_tasks)}")
    
    if not pending_tasks:
        log("[调度器] 没有待处理的任务")
        log("="*60)
        return 0, 0
    
    log(f"[调度器] 开始处理 {len(pending_tasks)} 个待处理任务")
    
    # 分批并行执行：每批最多 MAX_CONCURRENT_TASKS 个任务并发
    triggered = 0
    failed = 0
    
    log(f"\n[调度器] 开始分批并行执行，共 {len(pending_tasks)} 个任务，每批最多 {MAX_CONCURRENT_TASKS} 个")
    
    for batch_start in range(0, len(pending_tasks), MAX_CONCURRENT_TASKS):
        batch = pending_tasks[batch_start:batch_start + MAX_CONCURRENT_TASKS]
        batch_num = batch_start // MAX_CONCURRENT_TASKS + 1
        total_batches = (len(pending_tasks) + MAX_CONCURRENT_TASKS - 1) // MAX_CONCURRENT_TASKS
        
        log(f"\n[调度器] ========== 批次 {batch_num}/{total_batches}: {len(batch)} 个任务 ==========")
        for i, task in enumerate(batch):
            log(f"[调度器]   任务 {i+1}: [{task['agent']}] {task['title'][:40]}...")
        
        # 并行执行本批次所有任务（每个任务独立 WebSocket 连接）
        log(f"[调度器] 启动 asyncio.gather 并行执行...")
        results = await asyncio.gather(
            *[_execute_task_with_own_ws(task) for task in batch],
            return_exceptions=True
        )
        log(f"[调度器] asyncio.gather 完成，处理结果...")
        
        for i, r in enumerate(results):
            task_title = batch[i]['title'][:30]
            if isinstance(r, Exception):
                log(f"[调度器] ❌ 任务 {i+1} 异常: {r}")
                failed += 1
            elif r.get("success"):
                log(f"[调度器] ✅ 任务 {i+1} 成功: {task_title}")
                triggered += 1
            else:
                error = r.get('error', 'Unknown')
                log(f"[调度器] ❌ 任务 {i+1} 失败: {task_title}, 错误: {error}")
                failed += 1
        
        log(f"[调度器] ========== 批次 {batch_num} 完成 ==========")
    
    log(f"\n本次检查完成: 成功 {triggered} 个, 失败 {failed} 个")
    log("="*60)
    return triggered, failed


async def test_connection():
    """测试WebSocket连接"""
    print("测试WebSocket连接...")
    client = OpenClawGatewayClient()
    
    if await client.connect():
        print("✅ WebSocket连接成功")
        
        # 测试获取会话列表
        result = await client.request("sessions.list", {"limit": 5})
        if result.get("type") == "res":
            sessions = result.get("result", {}).get("sessions", [])
            print(f"✅ 获取会话列表成功: {len(sessions)} 个会话")
        else:
            print(f"⚠️ 获取会话列表: {result}")
        
        await client.close()
        return True
    else:
        print("❌ WebSocket连接失败")
        return False


# ============ 命令行接口 ============
def main():
    parser = argparse.ArgumentParser(description="GitHub Projects WebSocket 调度器 v3")
    parser.add_argument("--once", action="store_true", help="运行一次后退出")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    parser.add_argument("--test-connection", action="store_true", help="测试WebSocket连接")
    
    # Agent 调用参数
    parser.add_argument("--complete", metavar="ITEM_ID", help="标记任务完成（Agent调用）")
    parser.add_argument("--fail", metavar="ITEM_ID", help="标记任务失败（Agent调用）")
    parser.add_argument("--comment", metavar="ITEM_ID", help="添加评论到任务（Agent调用，配合--body）")
    parser.add_argument("--body", default="", help="评论内容（配合--comment使用）")
    
    args = parser.parse_args()
    
    global VERBOSE
    VERBOSE = args.verbose
    
    # 尝试从 openclaw.json 读取 token
    global DEFAULT_GATEWAY_TOKEN
    if not DEFAULT_GATEWAY_TOKEN:
        try:
            config_path = Path.home() / ".openclaw" / "openclaw.json"
            if config_path.exists():
                config = json.loads(config_path.read_text())
                DEFAULT_GATEWAY_TOKEN = config.get("gateway", {}).get("auth", {}).get("token", "")
        except Exception:
            pass
    
    # 处理 Agent 调用命令（--complete, --fail, --comment）
    if args.complete:
        success = complete_task(args.complete)
        sys.exit(0 if success else 1)
    
    if args.fail:
        success = fail_task(args.fail)
        sys.exit(0 if success else 1)
    
    if args.comment:
        if not args.body:
            print("❌ --comment 需要配合 --body 参数使用")
            sys.exit(1)
        success = add_task_comment(args.comment, args.body)
        sys.exit(0 if success else 1)
    
    # 启动时自动解析项目字段
    if not args.test_connection:
        log("正在解析项目字段配置...")
        if PROJECT_ID:
            resolve_project_fields()
    
    if args.test_connection:
        success = asyncio.run(test_connection())
        sys.exit(0 if success else 1)
    
    # 运行调度器
    triggered, failed = asyncio.run(check_and_trigger_tasks())
    
    if not args.once:
        log("\n进入持续模式（每60秒检查一次）...")
        while True:
            time.sleep(60)
            asyncio.run(check_and_trigger_tasks())
    
    # 如果有失败任务，返回非零退出码
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
