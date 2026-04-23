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

# 默认值
DEFAULT_CONFIG = {
    "gh_token": "",
    "project_id": "PVT_kwHOABOkaM4BVDrk",
    "status_field_id": "PVTSSF_lAHOABOkaM4BVDrkzhQiE3c",
    "agent_field_id": "PVTSSF_lAHOABOkaM4BVDrkzhQl13Y",
    "start_date_field_id": "PVTF_lAHOABOkaM4BVDrkzhQiE-c",
    "feishu_chat_id": "oc_xxx",
    "ws_url": "ws://127.0.0.1:18789",
    "gateway_token": ""
}

def load_config():
    """加载配置，优先级：环境变量 > 配置文件 > 默认值"""
    config = DEFAULT_CONFIG.copy()
    
    # 1. 从配置文件读取（项目目录，覆盖默认值）
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                file_config = json.load(f)
                # 只更新非空值
                for key, value in file_config.items():
                    if key in config and value:
                        config[key] = value
            print(f"✅ 已加载配置文件: {CONFIG_FILE}")
        except Exception as e:
            print(f"⚠️ 配置文件读取失败: {e}")
    else:
        print(f"⚠️ 配置文件不存在: {CONFIG_FILE}，使用默认值")
    
    # 2. 从环境变量读取（最高优先级，覆盖配置文件）
    env_mappings = {
        "gh_token": "GH_TOKEN",
        "project_id": "GH_PROJECT_ID",
        "feishu_chat_id": "GH_FEISHU_CHAT_ID",
        "gateway_token": "OPENCLAW_GATEWAY_TOKEN"
    }
    
    for config_key, env_key in env_mappings.items():
        env_value = os.environ.get(env_key, "")
        if env_value:
            config[config_key] = env_value
    
    return config

# 加载配置
CONFIG = load_config()

# ============ 配置项 ============
GH_TOKEN = CONFIG["gh_token"]
PROJECT_ID = CONFIG["project_id"]
STATUS_FIELD_ID = CONFIG["status_field_id"]
AGENT_FIELD_ID = CONFIG["agent_field_id"]
START_DATE_FIELD_ID = CONFIG["start_date_field_id"]
FEISHU_CHAT_ID = CONFIG["feishu_chat_id"]

STATUS_TODO = "f75ad846"
STATUS_IN_PROGRESS = "47fc9ee4"
STATUS_DONE = "98236657"
STATUS_FAILED = "a2aba7a8"

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

# WebSocket配置
DEFAULT_WS_URL = CONFIG["ws_url"]
DEFAULT_GATEWAY_TOKEN = CONFIG["gateway_token"]

VERBOSE = False

# ============ 日志 ============
def log(msg: str, force: bool = False):
    if VERBOSE or force:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {msg}", flush=True)


# 兼容旧代码的同步调用方式（在异步函数中使用）
def send_group_message(content: str):
    """发送群消息到飞书（同步包装，用于非异步上下文）"""
    # 注意：此函数只能在异步上下文中使用，通过 check_and_trigger_tasks 中的 client 调用
    # 这里只是打印日志，实际发送在 check_and_trigger_tasks 中完成
    print(f"[群消息] 准备发送: {content[:50]}...")


# ============ OpenClaw WebSocket 客户端 ============
class OpenClawGatewayClient:
    """OpenClaw Gateway WebSocket 客户端"""

    def __init__(self, url: str = None, token: str = None):
        self.url = url or DEFAULT_WS_URL
        self.token = token or DEFAULT_GATEWAY_TOKEN
        self.ws = None
        self.connect_nonce = None
        self.request_id = 0
        self.pending_requests = {}
        self.received_events = []

    async def connect(self) -> bool:
        """连接 Gateway 并完成握手"""
        try:
            self.ws = await websockets.connect(self.url)
            # 等待 connect.challenge
            while True:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=10)
                evt = json.loads(raw)
                if evt.get("event") == "connect.challenge":
                    self.connect_nonce = evt.get("payload", {}).get("nonce")
                    break
                self.received_events.append(evt)

            # 发送 connect 请求
            await self._send_connect()
            return True
        except Exception as e:
            log(f"WebSocket连接失败: {e}")
            return False

    async def _send_connect(self):
        """发送 connect 握手请求"""
        req_id = str(uuid.uuid4())
        frame = {
            "type": "req",
            "id": req_id,
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {
                    "id": "gateway-client",
                    "version": "1.0.0-test",
                    "platform": sys.platform,
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

        # 等待 hello.ok
        while True:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=10)
            msg = json.loads(raw)
            if msg.get("id") == req_id:
                if msg.get("type") == "res":
                    return msg
                elif msg.get("type") == "err":
                    raise Exception(f"connect failed: {msg}")
            self.received_events.append(msg)

    async def request(self, method: str, params: Dict = None, timeout: int = 60) -> Dict:
        """发送 RPC 请求并等待响应"""
        self.request_id += 1
        req_id = f"req-{self.request_id}"
        frame = {
            "type": "req",
            "id": req_id,
            "method": method,
            "params": params or {}
        }
        await self.ws.send(json.dumps(frame))

        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=2)
                msg = json.loads(raw)
                if msg.get("id") == req_id:
                    if msg.get("type") == "res" and msg.get("ok"):
                        return {"type": "res", "ok": True, "result": msg.get("payload", {})}
                    return msg
                self.received_events.append(msg)
            except asyncio.TimeoutError:
                continue
        return {"type": "timeout", "method": method}

    async def execute_agent_task(self, agent_id: str, task_title: str, task_body: str, 
                                  item_id: str, timeout: int = 300) -> Dict:
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
1. 首先读取 ~/.openclaw/workspace/ai-team/{agent_id}/SKILLS.md
2. 根据任务描述找到匹配的技能路由
3. 调用对应技能完成任务
4. **添加任务执行评论**（必须）：
   - 使用 GitHub API 或 feishu_doc_comments 工具在任务下添加评论
   - 评论内容包含：执行摘要、关键结果、遇到的问题
5. 执行成功后，更新GitHub状态为Done：
   python3 ~/.openclaw/workspace/skills/github-projects/task_scheduler_v2.py --complete {item_id} --agent {agent_id}
6. 如果执行失败，更新GitHub状态为Failed：
   python3 ~/.openclaw/workspace/skills/github-projects/task_scheduler_v2.py --fail {item_id}:失败原因 --agent {agent_id}
7. 在AI智能团队群里汇报结果（使用自己的飞书Bot账号）
8. 返回执行结果摘要

注意：
- 只有GitHub Projects任务需要更新状态
- **必须先添加评论，再更新状态**
- 完成后立即处理，不要等待主Agent
- 汇报时消息开头标注身份如【{agent_id}】
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
                            return {"error": msg.get("error", {}), "chunks": []}

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
                        log(f"任务执行完成，总耗时: {time.time() - t0:.1f}s")
                        break

                self.received_events.append(msg)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                log(f"接收消息出错: {e}")
                break

        return {
            "session_key": session_key,
            "run_id": run_id,
            "chunks": chunks,
            "final_state": final_state,
            "ttft": first_chunk,
            "elapsed": time.time() - t0
        }

    async def close(self):
        if self.ws:
            await self.ws.close()


# ============ GitHub API ============
def graphql_query(query: str, variables: Dict = None) -> Dict:
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
    items = data.get("node", {}).get("items", {}).get("nodes", [])
    
    result = []
    for item in items:
        parsed = {
            "id": item["id"],
            "title": item.get("content", {}).get("title", "无标题"),
            "body": item.get("content", {}).get("body", ""),
            "number": item.get("content", {}).get("number"),
            "state": item.get("content", {}).get("state"),
            "status": None,
            "agent": None,
            "start_date": None
        }
        
        for fv in item.get("fieldValues", {}).get("nodes", []):
            field_name = fv.get("field", {}).get("name", "")
            if field_name == "Status":
                parsed["status"] = fv.get("optionId")
            elif field_name == "Agent":
                parsed["agent"] = fv.get("optionId")
            elif field_name == "Start date":
                parsed["start_date"] = fv.get("date")
        
        result.append(parsed)
    
    return result


def update_item_status(item_id: str, status_option_id: str) -> bool:
    """更新任务状态"""
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
    
    return "errors" not in result


def get_agent_name_by_option_id(option_id: str) -> Optional[str]:
    """根据option ID获取Agent名称"""
    for name, oid in AGENT_OPTIONS.items():
        if oid == option_id:
            return name
    return None


# ============ 主调度逻辑 ============
async def check_and_trigger_tasks():
    """检查并触发任务（调度器主逻辑）"""
    log("\n" + "="*60)
    log("开始检查GitHub Projects任务...")
    
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items = get_project_items()
    
    triggered = 0
    failed = 0
    
    # 先过滤出需要处理的任务
    pending_tasks = []
    for item in items:
        item_id = item["id"]
        title = item["title"]
        status = item["status"]
        agent_option_id = item["agent"]
        start_date = item["start_date"]
        
        # 只处理 Todo 状态的任务
        if status != STATUS_TODO:
            continue
        
        # 检查开始时间
        if start_date and start_date > today:
            log(f"⏳ 任务未到期: {title[:30]}... (开始时间: {start_date})")
            continue
        
        # 获取Agent名称
        agent = get_agent_name_by_option_id(agent_option_id)
        if not agent:
            log(f"⚠️ 未知Agent: {agent_option_id}, 任务: {title[:30]}...")
            continue
        
        pending_tasks.append({
            "item_id": item_id,
            "title": title,
            "body": item.get("body", ""),
            "agent": agent
        })
    
    if not pending_tasks:
        log("没有待处理的任务")
        log("="*60)
        return 0, 0
    
    log(f"发现 {len(pending_tasks)} 个待处理任务")
    
    # 连接WebSocket
    client = OpenClawGatewayClient()
    if not await client.connect():
        log("❌ WebSocket连接失败，无法执行任务")
        return 0, len(pending_tasks)
    
    # 【汇报1】调度器启动 - 发现有任务，在群里汇报
    try:
        result = await client.request(
            "message.send",
            {
                "channel": "feishu",
                "target": f"chat:{FEISHU_CHAT_ID}",
                "message": f"🤖 【调度器启动】发现 {len(pending_tasks)} 个待处理任务，开始调度执行..."
            },
            timeout=10
        )
        if result.get("type") == "res" and result.get("ok"):
            print(f"[群消息] 发送成功")
    except Exception as e:
        print(f"[群消息] 异常: {e}")
    
    try:
        for task in pending_tasks:
            item_id = task["item_id"]
            title = task["title"]
            body = task["body"]
            agent = task["agent"]
            
            log(f"\n处理任务: [{agent}] {title[:50]}...")
            
            # 更新状态为 In progress（调度器只负责开始状态）
            if not update_item_status(item_id, STATUS_IN_PROGRESS):
                log(f"❌ 更新状态失败，跳过任务")
                failed += 1
                continue
            
            log(f"状态已更新为 In progress")
            
            # 通过WebSocket执行Agent任务
            # Agent自己会更新状态为 Done 或 Failed
            try:
                result = await client.execute_agent_task(
                    agent_id=agent,
                    task_title=title,
                    task_body=body,
                    item_id=item_id,
                    timeout=300  # 5分钟超时
                )
                
                if result.get("error"):
                    log(f"❌ Agent执行失败: {result['error']}")
                    # Agent执行异常，调度器将状态回滚为 Todo
                    update_item_status(item_id, STATUS_TODO)
                    failed += 1
                else:
                    reply = "".join(result.get("chunks", []))
                    log(f"✅ Agent执行完成")
                    log(f"回复摘要: {reply[:200]}..." if len(reply) > 200 else f"回复: {reply}")
                    log(f"Agent应已自行更新状态为 Done/Failed")
                    triggered += 1
                        
            except Exception as e:
                log(f"❌ 执行Agent任务异常: {e}")
                # Agent执行异常，调度器将状态回滚为 Todo
                update_item_status(item_id, STATUS_TODO)
                failed += 1
    # 【汇报2】执行完成 - 在群里汇报执行结果（在关闭连接前）
    if triggered > 0 or failed > 0:
        # 构建任务执行摘要
        task_summary = []
        for i, task in enumerate(pending_tasks[:5], 1):  # 最多显示5个
            status_icon = "✅" if i <= triggered else "❌"
            task_summary.append(f"{status_icon} [{task['agent']}] {task['title'][:30]}...")
        
        if len(pending_tasks) > 5:
            task_summary.append(f"... 还有 {len(pending_tasks) - 5} 个任务")
        
        summary_text = "\n".join(task_summary)
        
        try:
            result = await client.request(
                "message.send",
                {
                    "channel": "feishu",
                    "target": f"chat:{FEISHU_CHAT_ID}",
                    "message": f"""📋 【任务调度完成】

本次调度统计：
• 发现任务：{len(pending_tasks)} 个
• 成功执行：{triggered} 个
• 执行失败：{failed} 个

任务执行清单：
{summary_text}

⏳ 各 Agent 正在执行中，完成后将分别汇报结果..."""
                },
                timeout=10
            )
            if result.get("type") == "res" and result.get("ok"):
                print(f"[群消息] 发送成功")
        except Exception as e:
            print(f"[群消息] 异常: {e}")
    
    finally:
        await client.close()
    
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
