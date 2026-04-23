#!/usr/bin/env python3
"""
GitHub Projects 自动执行器

功能：
1. 每分钟轮询 GitHub Projects
2. 检查 Start date 字段，到达时间自动触发
3. 自动更新状态为 "In progress"
4. 自动启动对应 Agent 执行
5. Agent 完成后自动更新状态为 "Done"

使用方法：
    # 手动运行一次
    python3 auto_executor.py --once
    
    # 持续运行（由 HEARTBEAT 调用）
    python3 auto_executor.py

环境变量：
    GH_TOKEN: GitHub Token
"""

import os
import sys
import json
import time
import argparse
import requests
from datetime import datetime, timezone

# ============ 配置 ============
GH_TOKEN = os.environ.get("GH_TOKEN", "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")
PROJECT_ID = "PVT_kwHOABOkaM4BVDrk"
STATUS_FIELD_ID = "PVTSSF_lAHOABOkaM4BVDrkzhQiE3c"

STATUS_TODO = "f75ad846"
STATUS_IN_PROGRESS = "47fc9ee4"
STATUS_DONE = "98236657"

GRAPHQL_URL = "https://api.github.com/graphql"

# 已触发任务缓存
TRIGGERED_TASKS_FILE = "/tmp/gh_projects_triggered.json"


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
        return None
    
    data = response.json()
    if "errors" in data:
        print(f"GraphQL Error: {data['errors']}")
        return None
    
    return data.get("data")


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
                  state
                  url
                }}
              }}
              fieldValues(first: 20) {{
                nodes {{
                  ... on ProjectV2ItemFieldSingleSelectValue {{
                    field {{
                      ... on ProjectV2FieldCommon {{
                        name
                      }}
                    }}
                    optionId
                    name
                  }}
                  ... on ProjectV2ItemFieldDateValue {{
                    field {{
                      ... on ProjectV2FieldCommon {{
                        name
                      }}
                    }}
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


def parse_item_fields(item):
    """解析任务字段"""
    field_values = item.get("fieldValues", {}).get("nodes", [])
    
    result = {
        "agent": "main",
        "status": "Unknown",
        "start_date": None
    }
    
    for fv in field_values:
        field_name = fv.get("field", {}).get("name", "")
        
        if field_name == "Agent":
            result["agent"] = fv.get("name", "main")
        elif field_name == "Status":
            option_id = fv.get("optionId", "")
            if option_id == STATUS_TODO:
                result["status"] = "Todo"
            elif option_id == STATUS_IN_PROGRESS:
                result["status"] = "In progress"
            elif option_id == STATUS_DONE:
                result["status"] = "Done"
        elif field_name == "Start date":
            date_str = fv.get("date", "")
            if date_str:
                result["start_date"] = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    
    return result


def update_item_status(item_id, status_option_id):
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
        projectV2Item {
          id
        }
      }
    }
    """
    
    variables = {
        "projectId": PROJECT_ID,
        "itemId": item_id,
        "fieldId": STATUS_FIELD_ID,
        "optionId": status_option_id
    }
    
    return graphql_query(mutation, variables) is not None


def load_triggered_tasks():
    """加载已触发的任务"""
    if os.path.exists(TRIGGERED_TASKS_FILE):
        with open(TRIGGERED_TASKS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_triggered_tasks(tasks):
    """保存已触发的任务"""
    with open(TRIGGERED_TASKS_FILE, "w") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)


def should_trigger(item_id, fields, now):
    """判断是否应该触发任务"""
    # 条件1: 状态是 Todo
    if fields["status"] != "Todo":
        return False
    
    # 条件2: 有开始日期
    if not fields["start_date"]:
        return False
    
    # 条件3: 开始时间 <= 现在
    if fields["start_date"] > now:
        return False
    
    return True


def trigger_task(item, fields):
    """触发任务执行"""
    content = item.get("content", {})
    item_id = item.get("id", "")
    title = content.get("title", "")
    body = content.get("body", "")
    agent = fields["agent"]
    
    print(f"\n{'='*60}")
    print(f"🚀 触发任务")
    print(f"{'='*60}")
    print(f"   标题: {title}")
    print(f"   Agent: {agent}")
    print(f"   开始时间: {fields['start_date']}")
    
    # Step 1: 更新 GitHub 状态为 In progress
    print(f"\n⏳ 更新 GitHub 状态: In progress...")
    if update_item_status(item_id, STATUS_IN_PROGRESS):
        print("   ✅ 状态已更新")
    else:
        print("   ❌ 状态更新失败")
        return False
    
    # Step 2: 生成任务文件
    task_file = f"/tmp/gh_project_task_{item_id.replace('/', '_')}_{int(time.time())}.json"
    task_data = {
        "item_id": item_id,
        "agent_id": agent,
        "title": title,
        "body": body,
        "start_date": fields["start_date"].isoformat() if fields["start_date"] else None,
        "status": "in_progress",
        "triggered_at": datetime.now().isoformat()
    }
    
    with open(task_file, "w") as f:
        json.dump(task_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n📄 任务文件: {task_file}")
    
    # Step 3: 启动 Agent（使用 sessions_spawn）
    print(f"\n🤖 启动 Agent: {agent}")
    
    task_desc = f"""【GitHub Projects 自动任务】

任务ID: {item_id}
标题: {title}
描述: {body}
分配Agent: {agent}
开始时间: {fields.get('start_date')}

请执行以下步骤：
1. 读取 ~/.openclaw/workspace/ai-team/{agent}/SKILLS.md
2. 根据任务描述，找到匹配的技能路由规则
3. 调用相应技能完成任务
4. 完成后运行: python3 ~/.openclaw/workspace/skills/github-projects/execute_task.py --item-id {item_id} --complete
"""
    
    print(f"\n{'='*60}")
    print(f"📝 任务描述:")
    print(f"{'='*60}")
    print(task_desc)
    print(f"{'='*60}")
    print(f"\n⚠️  Agent 执行需要手动启动:")
    print(f"   方式1: sessions_spawn 启动 {agent} Agent")
    print(f"   方式2: 直接运行对应技能")
    
    return task_file


def main():
    parser = argparse.ArgumentParser(description="GitHub Projects 自动执行器")
    parser.add_argument("--once", action="store_true", help="只执行一次")
    parser.add_argument("--interval", type=int, default=1, help="轮询间隔(分钟)")
    args = parser.parse_args()
    
    print("=" * 60)
    print("🤖 GitHub Projects 自动执行器")
    print("=" * 60)
    print(f"Project ID: {PROJECT_ID}")
    print(f"轮询间隔: {args.interval} 分钟")
    print("=" * 60)
    
    while True:
        print(f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - 检查任务...")
        
        # 获取所有任务
        items = get_project_items()
        print(f"📊 共 {len(items)} 个任务")
        
        # 加载已触发任务
        triggered = load_triggered_tasks()
        
        # 当前时间
        now = datetime.now(timezone.utc)
        
        # 检查每个任务
        new_triggers = 0
        for item in items:
            content = item.get("content", {})
            if not content:
                continue
            
            item_id = item.get("id", "")
            title = content.get("title", "")
            
            # 解析字段
            fields = parse_item_fields(item)
            
            # 检查是否应该触发
            if should_trigger(item_id, fields, now):
                # 检查是否已经触发过
                if item_id not in triggered:
                    print(f"\n✨ 发现可触发任务: {title}")
                    
                    # 触发任务
                    task_file = trigger_task(item, fields)
                    
                    # 记录已触发
                    triggered[item_id] = {
                        "title": title,
                        "agent": fields["agent"],
                        "triggered_at": datetime.now().isoformat(),
                        "task_file": task_file
                    }
                    new_triggers += 1
        
        # 保存触发记录
        save_triggered_tasks(triggered)
        
        if new_triggers > 0:
            print(f"\n🎯 本次触发 {new_triggers} 个任务")
        else:
            print(f"\n✅ 没有新任务需要触发")
        
        if args.once:
            break
        
        # 等待下一轮
        print(f"\n💤 等待 {args.interval} 分钟后再次检查...")
        time.sleep(args.interval * 60)


if __name__ == "__main__":
    main()
