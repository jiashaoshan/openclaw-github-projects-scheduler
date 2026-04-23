#!/usr/bin/env python3
"""
GitHub Projects ↔ OpenClaw 联动同步脚本（带飞书通知）

功能：
1. 查询 GitHub Projects 任务
2. 检测状态为 "In progress" 的任务
3. 发送飞书卡片消息通知
4. 用户确认后触发 Agent 执行
5. 自动更新任务状态

使用方法：
    python3 sync_with_notification.py [--once] [--interval 1]

环境变量：
    GH_TOKEN: GitHub Personal Access Token (需要 project 权限)
    FEISHU_CHAT_ID: 飞书群 ID (可选，默认发送到当前对话)
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

# 已处理的任务缓存（避免重复通知）
PROCESSED_ITEMS_FILE = "/tmp/gh_projects_processed.json"

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


def load_processed_items():
    """加载已处理的任务列表"""
    if os.path.exists(PROCESSED_ITEMS_FILE):
        with open(PROCESSED_ITEMS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_processed_items(items):
    """保存已处理的任务列表"""
    with open(PROCESSED_ITEMS_FILE, "w") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def generate_task_card(item, agent):
    """生成飞书卡片消息"""
    content = item.get("content", {})
    title = content.get("title", "")
    body = content.get("body", "")[:200]  # 截断长文本
    item_id = item.get("id", "")
    
    card = {
        "config": {
            "wide_screen_mode": True
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"🚀 GitHub Projects 任务触发"
            },
            "template": "blue"
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**任务:** {title}"
                }
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**Agent:** {agent}"
                }
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**任务ID:** `{item_id}`"
                }
            },
            {
                "tag": "hr"
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**描述:**\n{body if body else '无描述'}"
                }
            },
            {
                "tag": "hr"
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "✅ 确认执行"
                        },
                        "type": "primary",
                        "value": {
                            "action": "execute",
                            "item_id": item_id,
                            "agent": agent,
                            "title": title
                        }
                    },
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "❌ 忽略"
                        },
                        "type": "default",
                        "value": {
                            "action": "ignore",
                            "item_id": item_id
                        }
                    }
                ]
            }
        ]
    }
    
    return card


def dispatch_to_agent(item, agent):
    """分发任务给 Agent"""
    content = item.get("content", {})
    title = content.get("title", "")
    body = content.get("body", "")
    item_id = item.get("id", "")
    
    print(f"\n{'='*60}")
    print(f"🚀 开始执行任务")
    print(f"{'='*60}")
    print(f"   标题: {title}")
    print(f"   Agent: {agent}")
    print(f"   任务ID: {item_id}")
    
    # Step 1: 更新状态为 "In progress"
    print(f"\n⏳ 更新 GitHub 状态: In progress...")
    if update_item_status(item_id, STATUS_IN_PROGRESS):
        print("   ✅ GitHub 状态已更新")
    else:
        print("   ❌ GitHub 状态更新失败")
        return False
    
    # Step 2: 构建任务描述
    task_desc = f"""【GitHub Projects 任务执行】

任务ID: {item_id}
标题: {title}
描述: {body}
分配Agent: {agent}

请执行以下步骤：
1. 读取 ~/.openclaw/workspace/ai-team/{agent}/SKILLS.md
2. 根据任务描述，找到匹配的技能路由规则
3. 调用相应技能完成任务
4. 返回执行结果摘要

注意：
- 如果任务描述不够具体，请先向用户确认
- 执行完成后，运行以下命令标记完成：
  python3 ~/.openclaw/workspace/skills/github-projects/execute_task.py --item-id {item_id} --complete
"""
    
    # Step 3: 保存任务信息
    task_file = f"/tmp/gh_project_task_{item_id.replace('/', '_')}.json"
    with open(task_file, "w") as f:
        json.dump({
            "item_id": item_id,
            "agent_id": agent,
            "title": title,
            "body": body,
            "task_desc": task_desc,
            "status": "in_progress",
            "created_at": datetime.now().isoformat()
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n📄 任务文件: {task_file}")
    print(f"\n🤖 Agent: {agent}")
    print(f"\n请手动启动 Agent 执行:")
    print(f"   方式1: 直接运行 sync_with_notification.py --execute {task_file}")
    print(f"   方式2: 使用 sessions_spawn 启动 {agent} Agent")
    
    return task_file


def process_items(items, notify=True):
    """处理所有任务"""
    processed = load_processed_items()
    new_tasks = []
    
    for item in items:
        content = item.get("content", {})
        if not content:
            continue
        
        title = content.get("title", "")
        item_id = item.get("id", "")
        
        # 解析当前状态
        status = parse_item_status(item)
        agent = parse_item_agent(item)
        
        # 只处理 "In progress" 状态且未通知过的任务
        if status == "In progress" and item_id not in processed:
            print(f"\n📋 新任务: [{agent}] {title}")
            
            if notify:
                # 生成飞书卡片
                card = generate_task_card(item, agent)
                print(f"\n📨 飞书卡片消息已生成")
                print(f"   请确认是否执行此任务")
                
                # 保存到待处理队列
                new_tasks.append({
                    "item_id": item_id,
                    "agent": agent,
                    "title": title,
                    "card": card
                })
            
            # 标记为已处理
            processed[item_id] = {
                "title": title,
                "agent": agent,
                "status": status,
                "notified_at": datetime.now().isoformat()
            }
    
    save_processed_items(processed)
    return new_tasks


def main():
    parser = argparse.ArgumentParser(description="GitHub Projects ↔ OpenClaw 联动（带通知）")
    parser.add_argument("--once", action="store_true", help="只执行一次")
    parser.add_argument("--interval", type=int, default=1, help="轮询间隔(分钟)")
    parser.add_argument("--execute", type=str, help="执行指定任务文件")
    parser.add_argument("--notify-only", action="store_true", help="仅发送通知，不自动执行")
    args = parser.parse_args()
    
    if args.execute:
        # 执行指定任务
        with open(args.execute, "r") as f:
            task = json.load(f)
        
        item_id = task.get("item_id")
        agent_id = task.get("agent_id")
        title = task.get("title")
        
        print(f"\n{'='*60}")
        print(f"🚀 执行任务: {title}")
        print(f"{'='*60}")
        print(f"   Agent: {agent_id}")
        print(f"   任务ID: {item_id}")
        print(f"\n请使用 sessions_spawn 启动 {agent_id} Agent")
        print(f"   任务描述已保存到: {args.execute}")
        return
    
    print("=" * 60)
    print("🔗 GitHub Projects ↔ OpenClaw 联动系统（带通知）")
    print("=" * 60)
    print(f"Project ID: {PROJECT_ID}")
    print(f"轮询间隔: {args.interval} 分钟")
    print(f"通知模式: {'仅通知' if args.notify_only else '通知+自动执行'}")
    print("=" * 60)
    
    while True:
        print(f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - 开始同步...")
        
        # 获取任务列表
        items = get_project_items()
        print(f"📊 共 {len(items)} 个任务")
        
        # 处理任务
        new_tasks = process_items(items, notify=True)
        
        if new_tasks:
            print(f"\n🎯 发现 {len(new_tasks)} 个新任务")
            for task in new_tasks:
                print(f"   - [{task['agent']}] {task['title']}")
                
                if not args.notify_only:
                    # 找到对应的 item 并执行
                    for item in items:
                        if item.get("id") == task["item_id"]:
                            dispatch_to_agent(item, task["agent"])
                            break
        else:
            print(f"\n✅ 没有新任务")
        
        if args.once:
            break
        
        # 等待下一轮
        print(f"\n💤 等待 {args.interval} 分钟后再次同步...")
        time.sleep(args.interval * 60)


if __name__ == "__main__":
    main()
