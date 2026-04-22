#!/usr/bin/env python3
"""
GitHub Projects 智能任务调度器 v2（零Token消耗版 - 任务文件方式）

功能：
1. 纯Python轮询，不调用LLM（零Token消耗）
2. 发现待执行任务时，创建任务文件到 /tmp/gh_tasks/{agent}/
3. Agent通过HEARTBEAT检查任务文件并执行
4. Agent执行完成后自行更新GitHub状态

架构：
    系统cron(每分钟) → 调度器(零Token) → 创建任务文件
                                           ↓
    Agent HEARTBEAT(检查文件) → 有任务? → 执行 → 更新GitHub

使用方法：
    # 系统cron定时调用（每分钟）
    * * * * * /usr/bin/python3 /path/to/task_scheduler_v2.py --once >> /tmp/gh_scheduler.log 2>&1
    
    # 手动测试
    python3 task_scheduler_v2.py --verbose
"""

import os
import sys
import json
import argparse
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

# ============ 配置 ============
GH_TOKEN = os.environ.get("GH_TOKEN", "")
PROJECT_ID = "PVT_kwHOABOkaM4BVDrk"
STATUS_FIELD_ID = "PVTSSF_lAHOABOkaM4BVDrkzhQiE3c"

STATUS_TODO = "f75ad846"
STATUS_IN_PROGRESS = "47fc9ee4"
STATUS_DONE = "98236657"
STATUS_FAILED = "a2aba7a8"

AGENT_FIELD_ID = "PVTSSF_lAHOABOkaM4BVDrkzhQl13Y"
START_DATE_FIELD_ID = "PVTF_lAHOABOkaM4BVDrkzhQiE-c"

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

TASKS_DIR = Path("/tmp/gh_tasks")
STATE_FILE = "/tmp/gh_scheduler_state.json"

VERBOSE = False

def log(msg: str, force: bool = False):
    if VERBOSE or force:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {msg}", flush=True)

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
    for name, oid in AGENT_OPTIONS.items():
        if oid == option_id:
            return name
    return None

# ============ 任务文件管理 ============

def ensure_tasks_dir():
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    for agent in AGENT_OPTIONS.keys():
        (TASKS_DIR / agent).mkdir(exist_ok=True)


def create_task_file(agent: str, title: str, body: str, item_id: str) -> bool:
    ensure_tasks_dir()
    task_file = TASKS_DIR / agent / f"{item_id.replace(':', '_')}.json"
    
    task_data = {
        "item_id": item_id,
        "title": title,
        "body": body,
        "agent": agent,
        "created_at": datetime.now().isoformat(),
        "status": "pending"
    }
    
    try:
        with open(task_file, 'w') as f:
            json.dump(task_data, f, ensure_ascii=False, indent=2)
        log(f"✅ 创建任务文件: {task_file}", True)
        return True
    except Exception as e:
        log(f"❌ 创建任务文件失败: {e}", True)
        return False


def list_pending_tasks(agent: str) -> List[Dict]:
    """供Agent HEARTBEAT调用 - 列出待处理任务"""
    agent_dir = TASKS_DIR / agent
    if not agent_dir.exists():
        return []
    
    tasks = []
    for task_file in agent_dir.glob("*.json"):
        try:
            with open(task_file) as f:
                task = json.load(f)
            if task.get("status") == "pending":
                task["_file"] = str(task_file)
                tasks.append(task)
        except Exception as e:
            log(f"读取任务文件失败: {task_file}, {e}")
    
    return tasks


def mark_task_processing(agent: str, item_id: str) -> bool:
    """标记任务为处理中"""
    task_file = TASKS_DIR / agent / f"{item_id.replace(':', '_')}.json"
    if not task_file.exists():
        return False
    
    try:
        with open(task_file) as f:
            task = json.load(f)
        task["status"] = "processing"
        task["started_at"] = datetime.now().isoformat()
        with open(task_file, 'w') as f:
            json.dump(task, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log(f"标记任务处理中失败: {e}")
        return False


def complete_task_file(agent: str, item_id: str, success: bool = True, result: str = ""):
    """完成任务文件（Agent调用）"""
    task_file = TASKS_DIR / agent / f"{item_id.replace(':', '_')}.json"
    if not task_file.exists():
        return False
    
    try:
        with open(task_file) as f:
            task = json.load(f)
        task["status"] = "completed" if success else "failed"
        task["completed_at"] = datetime.now().isoformat()
        task["result"] = result
        with open(task_file, 'w') as f:
            json.dump(task, f, ensure_ascii=False, indent=2)
        
        # 移动到归档目录
        archive_dir = TASKS_DIR / agent / "archive"
        archive_dir.mkdir(exist_ok=True)
        archive_file = archive_dir / f"{item_id.replace(':', '_')}_{int(datetime.now().timestamp())}.json"
        task_file.rename(archive_file)
        
        return True
    except Exception as e:
        log(f"完成任务文件失败: {e}")
        return False


# ============ 主逻辑 ============

def check_and_trigger_tasks():
    """检查并触发任务（调度器主逻辑）"""
    log("\n" + "="*60)
    log("开始检查任务...")
    
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items = get_project_items()
    
    triggered = 0
    
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
        
        # 检查是否已创建任务文件
        task_file = TASKS_DIR / agent / f"{item_id.replace(':', '_')}.json"
        if task_file.exists():
            log(f"⏭️ 任务文件已存在: {title[:30]}...")
            continue
        
        # 更新状态为 In progress
        if not update_item_status(item_id, STATUS_IN_PROGRESS):
            log(f"❌ 更新状态失败: {title[:30]}...")
            continue
        
        # 创建任务文件
        body = item.get("body", "")
        if create_task_file(agent, title, body, item_id):
            triggered += 1
            log(f"✅ 已创建任务文件: [{agent}] {title[:40]}...")
        else:
            # 创建失败，回滚状态
            update_item_status(item_id, STATUS_TODO)
    
    log(f"\n本次检查完成: 触发 {triggered} 个任务")
    log("="*60)
    return triggered


# ============ 命令行接口 ============

def main():
    parser = argparse.ArgumentParser(description="GitHub Projects 任务调度器 v2")
    parser.add_argument("--once", action="store_true", help="运行一次后退出")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    parser.add_argument("--complete", metavar="ITEM_ID", help="标记任务完成（Agent调用）")
    parser.add_argument("--fail", metavar="ITEM_ID", help="标记任务失败（Agent调用）")
    parser.add_argument("--agent", default="main", help="指定Agent（用于--complete/--fail）")
    
    args = parser.parse_args()
    
    global VERBOSE
    VERBOSE = args.verbose
    
    if args.complete:
        # Agent调用：标记任务完成
        if update_item_status(args.complete, STATUS_DONE):
            complete_task_file(args.agent, args.complete, success=True)
            log(f"✅ 任务已标记完成: {args.complete}", True)
        else:
            log(f"❌ 标记完成失败: {args.complete}", True)
            sys.exit(1)
    
    elif args.fail:
        # Agent调用：标记任务失败
        reason = ""  # 可以从其他地方获取失败原因
        if update_item_status(args.fail, STATUS_FAILED):
            complete_task_file(args.agent, args.fail, success=False, result=reason)
            log(f"✅ 任务已标记失败: {args.fail}", True)
        else:
            log(f"❌ 标记失败失败: {args.fail}", True)
            sys.exit(1)
    
    else:
        # 调度器模式
        check_and_trigger_tasks()
        
        if not args.once:
            log("\n进入持续模式（每60秒检查一次）...")
            import time
            while True:
                time.sleep(60)
                check_and_trigger_tasks()


if __name__ == "__main__":
    main()