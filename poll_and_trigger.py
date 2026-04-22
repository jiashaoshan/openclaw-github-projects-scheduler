#!/usr/bin/env python3
"""
GitHub Projects 轮询触发器（零 Token 消耗版）

功能：
1. 纯 Python 轮询，不调用 LLM
2. 只有发现待触发任务时，才调用 OpenClaw
3. 无任务时静默退出，零成本

使用方法：
    # 由 HEARTBEAT 每分钟调用
    python3 poll_and_trigger.py
    
    # 手动测试
    python3 poll_and_trigger.py --verbose

环境变量：
    GH_TOKEN: GitHub Token
"""

import os
import sys
import json
import argparse
import requests
import subprocess
from datetime import datetime, timezone

# ============ 配置 ============
GH_TOKEN = os.environ.get("GH_TOKEN", "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")
PROJECT_ID = "PVT_kwHOABOkaM4BVDrk"
STATUS_FIELD_ID = "PVTSSF_lAHOABOkaM4BVDrkzhQiE3c"

STATUS_TODO = "f75ad846"
STATUS_IN_PROGRESS = "47fc9ee4"
STATUS_DONE = "98236657"

GRAPHQL_URL = "https://api.github.com/graphql"
TRIGGERED_FILE = "/tmp/gh_projects_triggered.json"


def log(msg, verbose=False):
    """日志输出"""
    if verbose or os.environ.get("VERBOSE"):
        print(msg)


def graphql_query(query, variables=None):
    """执行 GraphQL 查询"""
    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json"
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    
    try:
        response = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=10)
        if response.status_code != 200:
            log(f"HTTP Error: {response.status_code}", True)
            return None
        
        data = response.json()
        if "errors" in data:
            log(f"GraphQL Error: {data['errors']}", True)
            return None
        
        return data.get("data")
    except Exception as e:
        log(f"Request Error: {e}", True)
        return None


def get_project_items():
    """获取所有任务"""
    query = f"""
    query {{
      node(id: "{PROJECT_ID}") {{
        ... on ProjectV2 {{
          items(first: 100) {{
            nodes {{
              id
              content {{
                ... on DraftIssue {{
                  id
                  title
                  body
                }}
                ... on Issue {{
                  id
                  number
                  title
                  body
                }}
              }}
              fieldValues(first: 20) {{
                nodes {{
                  ... on ProjectV2ItemFieldSingleSelectValue {{
                    field {{ ... on ProjectV2FieldCommon {{ name }} }}
                    optionId
                    name
                  }}
                  ... on ProjectV2ItemFieldDateValue {{
                    field {{ ... on ProjectV2FieldCommon {{ name }} }}
                    date
                  }}
                }}
              }}
            }}
          }}
        }}
      }}
    }}
    """
    
    data = graphql_query(query)
    if not data:
        return []
    
    return data.get("node", {}).get("items", {}).get("nodes", [])


def parse_fields(item):
    """解析字段"""
    field_values = item.get("fieldValues", {}).get("nodes", [])
    result = {"agent": "main", "status": "Unknown", "start_date": None}
    
    for fv in field_values:
        name = fv.get("field", {}).get("name", "")
        if name == "Agent":
            result["agent"] = fv.get("name", "main")
        elif name == "Status":
            oid = fv.get("optionId", "")
            if oid == STATUS_TODO:
                result["status"] = "Todo"
            elif oid == STATUS_IN_PROGRESS:
                result["status"] = "In progress"
            elif oid == STATUS_DONE:
                result["status"] = "Done"
        elif name == "Start date":
            date_str = fv.get("date", "")
            if date_str:
                result["start_date"] = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    
    return result


def load_triggered():
    """加载已触发记录"""
    if os.path.exists(TRIGGERED_FILE):
        with open(TRIGGERED_FILE, "r") as f:
            return json.load(f)
    return {}


def save_triggered(data):
    """保存已触发记录"""
    with open(TRIGGERED_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False)


def update_status(item_id, status_id):
    """更新状态"""
    mutation = """
    mutation($p: ID!, $i: ID!, $f: ID!, $o: String!) {
      updateProjectV2ItemFieldValue(
        input: {projectId: $p, itemId: $i, fieldId: $f, value: {singleSelectOptionId: $o}}
      ) { projectV2Item { id } }
    }
    """
    
    result = graphql_query(mutation, {
        "p": PROJECT_ID,
        "i": item_id,
        "f": STATUS_FIELD_ID,
        "o": status_id
    })
    
    return result is not None


def call_openclaw(agent, title, item_id, body):
    """调用 OpenClaw 启动 Agent"""
    log(f"\n🚀 调用 OpenClaw 启动 {agent} Agent", True)
    log(f"   任务: {title}", True)
    
    # 构建任务描述
    task = f"""【GitHub Projects 自动任务】

任务ID: {item_id}
标题: {title}
描述: {body}
分配Agent: {agent}

请立即执行此任务。
1. 读取 ~/.openclaw/workspace/ai-team/{agent}/SKILLS.md
2. 根据任务描述执行对应技能
3. 完成后汇报结果
"""
    
    # 使用 sessions_spawn 启动子 Agent
    # 注意：这里需要 OpenClaw 的 API 或命令行工具
    # 暂时输出到 stdout，由调用者处理
    print(f"\n{'='*60}")
    print(f"🎯 需要启动 Agent: {agent}")
    print(f"{'='*60}")
    print(f"任务: {title}")
    print(f"任务ID: {item_id}")
    print(f"\n请手动执行:")
    print(f"   sessions_spawn --agent {agent} --task '{task}'")
    print(f"{'='*60}\n")
    
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    args = parser.parse_args()
    
    log(f"⏰ {datetime.now().strftime('%H:%M:%S')} 检查 GitHub Projects...", args.verbose)
    
    # 获取任务
    items = get_project_items()
    if not items:
        log("❌ 获取任务失败", args.verbose)
        return 1
    
    log(f"📊 共 {len(items)} 个任务", args.verbose)
    
    # 加载已触发
    triggered = load_triggered()
    
    # 当前时间
    now = datetime.now(timezone.utc)
    
    # 检查任务
    to_trigger = []
    for item in items:
        content = item.get("content", {})
        if not content:
            continue
        
        item_id = item.get("id", "")
        title = content.get("title", "")
        body = content.get("body", "")
        
        fields = parse_fields(item)
        
        # 判断是否应该触发
        if (fields["status"] == "Todo" and 
            fields["start_date"] and 
            fields["start_date"] <= now and
            item_id not in triggered):
            
            to_trigger.append({
                "item_id": item_id,
                "title": title,
                "body": body,
                "agent": fields["agent"],
                "start_date": fields["start_date"].isoformat()
            })
    
    if not to_trigger:
        log("✅ 无任务需要触发", args.verbose)
        return 0
    
    log(f"\n🎯 发现 {len(to_trigger)} 个待触发任务:", True)
    
    # 触发任务
    for task in to_trigger:
        log(f"\n  📌 {task['title']} → {task['agent']}", True)
        
        # 更新状态为 In progress
        if update_status(task["item_id"], STATUS_IN_PROGRESS):
            log("     ✅ GitHub 状态已更新", True)
        else:
            log("     ❌ GitHub 状态更新失败", True)
            continue
        
        # 调用 OpenClaw
        if call_openclaw(task["agent"], task["title"], task["item_id"], task["body"]):
            # 记录已触发
            triggered[task["item_id"]] = {
                "title": task["title"],
                "agent": task["agent"],
                "triggered_at": datetime.now