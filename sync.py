#!/usr/bin/env python3
"""
GitHub Projects ↔ OpenClaw 联动同步脚本

功能：
1. 查询 GitHub Projects 任务
2. 检测状态为 "In progress" 的任务
3. 根据 Label 匹配 Agent 并分发任务
4. 监听 Agent 执行结果，更新任务状态

使用方法：
    python3 sync.py [--once] [--interval 5]

环境变量：
    GH_TOKEN: GitHub Personal Access Token (需要 project 权限)
"""

import os
import sys
import json
import time
import argparse
import requests
from datetime import datetime

# ============ 配置 ============
GH_TOKEN = os.environ.get("GH_TOKEN", "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")
PROJECT_ID = "PVT_kwHOABOkaM4BVDrk"
STATUS_FIELD_ID = "PVTSSF_lAHOABOkaM4BVDrkzhQiE3c"
AGENT_FIELD_ID = "PVTSSF_lAHOABOkaM4BVDrkzhQl13Y"

# Status Option IDs
STATUS_TODO = "f75ad846"
STATUS_IN_PROGRESS = "47fc9ee4"
STATUS_DONE = "98236657"

# Agent 字段选项 ID 映射
AGENT_OPTIONS = {
    "marketing": None,
    "content": None,
    "dev": None,
    "consultant": None,
    "finance": None,
    "operations": None,
    "ops": None,
    "hermes": None,
    "main": None,
}

GRAPHQL_URL = "https://api.github.com/graphql"

# ============ GraphQL 查询 ============

QUERY_PROJECT_ITEMS = """
query {
  node(id: "%s") {
    ... on ProjectV2 {
      items(first: 50) {
        nodes {
          id
          content {
            ... on DraftIssue {
              id
              title
              body
            }
            ... on Issue {
              id
              number
              title
              body
              state
              url
            }
          }
          fieldValues(first: 10) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                field {
                  ... on ProjectV2FieldCommon {
                    name
                  }
                }
                optionId
                name
              }
            }
          }
        }
      }
    }
  }
}
""" % PROJECT_ID

MUTATION_UPDATE_STATUS = """
mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
  updateProjectV2ItemFieldValue(
    input: {
      projectId: $projectId
      itemId: $itemId
      fieldId: $fieldId
      value: { singleSelectOptionId: $optionId }
    }
  ) {
    projectV2Item {
      id
    }
  }
}
"""

# ============ 核心函数 ============

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
    
    response = requests.post(GRAPHQL_URL, json=payload, headers=headers)
    if response.status_code != 200:
        print(f"❌ HTTP Error: {response.status_code}")
        print(response.text)
        return None
    
    data = response.json()
    if "errors" in data:
        print(f"❌ GraphQL Errors: {data['errors']}")
        return None
    
    return data.get("data")


def get_project_items():
    """获取 Projects 所有任务"""
    data = graphql_query(QUERY_PROJECT_ITEMS)
    if not data:
        return []
    
    items = data.get("node", {}).get("items", {}).get("nodes", [])
    return items


def parse_item_status(item):
    """解析任务当前状态"""
    field_values = item.get("fieldValues", {}).get("nodes", [])
    for fv in field_values:
        field_name = fv.get("field", {}).get("name", "")
        if field_name == "Status":
            option_id = fv.get("optionId")
            if option_id == STATUS_TODO:
                return "Todo"
            elif option_id == STATUS_IN_PROGRESS:
                return "In progress"
            elif option_id == STATUS_DONE:
                return "Done"
    return "Unknown"


def parse_item_agent(item):
    """解析任务分配的 Agent (从 Agent 字段)"""
    field_values = item.get("fieldValues", {}).get("nodes", [])
    
    # 从 Agent 字段读取
    for fv in field_values:
        field_name = fv.get("field", {}).get("name", "")
        if field_name == "Agent":
            agent_name = fv.get("name", "")
            if agent_name:
                return agent_name
    
    # 默认返回 main (总调度)
    return "main"


def update_item_status(item_id, status_option_id):
    """更新任务状态"""
    variables = {
        "projectId": PROJECT_ID,
        "itemId": item_id,
        "fieldId": STATUS_FIELD_ID,
        "optionId": status_option_id
    }
    
    data = graphql_query(MUTATION_UPDATE_STATUS, variables)
    return data is not None


def dispatch_to_agent(item, agent_id):
    """
    分发任务给 Agent
    这里生成一个任务描述文件，供外部调用 sessions_spawn 使用
    """
    content = item.get("content", {})
    title = content.get("title", "")
    body = content.get("body", "")
    item_id = item.get("id", "")
    
    task_desc = f"""
【GitHub Projects 任务】

任务ID: {item_id}
标题: {title}
描述: {body}

请按以下步骤执行：
1. 读取 ~/.openclaw/workspace/ai-team/{agent_id}/SKILLS.md
2. 根据任务描述，找到匹配的技能路由规则
3. 调用相应技能完成任务
4. 完成后更新 GitHub Projects 状态为 "Done"

任务来源: GitHub Projects V2
"""
    
    # 保存任务描述到文件，供后续处理
    task_file = f"/tmp/gh_project_task_{item_id.replace('/', '_')}.json"
    with open(task_file, "w") as f:
        json.dump({
            "item_id": item_id,
            "agent_id": agent_id,
            "title": title,
            "body": body,
            "task_desc": task_desc,
            "created_at": datetime.now().isoformat()
        }, f, ensure_ascii=False, indent=2)
    
    print(f"  📄 任务已保存: {task_file}")
    print(f"  🚀 请手动执行: sessions_spawn 启动 {agent_id} Agent")
    
    return task_file


def process_items(items):
    """处理所有任务"""
    processed = 0
    
    for item in items:
        content = item.get("content", {})
        if not content:
            continue
        
        title = content.get("title", "")
        item_id = item.get("id", "")
        
        # 解析当前状态
        status = parse_item_status(item)
        
        print(f"\n📋 [{status}] {title}")
        
        # 只处理 "In progress" 状态的任务
        if status == "In progress":
            agent_id = parse_item_agent(item)
            print(f"  🤖 匹配 Agent: {agent_id}")
            
            # 分发任务
            task_file = dispatch_to_agent(item, agent_id)
            processed += 1
    
    return processed


def main():
    parser = argparse.ArgumentParser(description="GitHub Projects ↔ OpenClaw 联动")
    parser.add_argument("--once", action="store_true", help="只执行一次")
    parser.add_argument("--interval", type=int, default=5, help="轮询间隔(分钟)")
    args = parser.parse_args()
    
    print("=" * 60)
    print("🔗 GitHub Projects ↔ OpenClaw 联动系统")
    print("=" * 60)
    print(f"Project ID: {PROJECT_ID}")
    print(f"轮询间隔: {args.interval} 分钟")
    print("=" * 60)
    
    while True:
        print(f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - 开始同步...")
        
        # 获取任务列表
        items = get_project_items()
        print(f"📊 共 {len(items)} 个任务")
        
        # 处理任务
        processed = process_items(items)
        print(f"\n✅ 本次处理 {processed} 个待执行任务")
        
        if args.once:
            break
        
        # 等待下一轮
        print(f"\n💤 等待 {args.interval} 分钟后再次同步...")
        time.sleep(args.interval * 60)


if __name__ == "__main__":
    main()
