#!/usr/bin/env python3
"""
执行任务并更新状态

使用方法：
    python3 execute_task.py --file /tmp/gh_project_task_xxx.json
    
或手动指定：
    python3 execute_task.py --item-id PVTI_xxx --agent dev --title "任务标题"
"""

import os
import sys
import json
import argparse
import requests
import subprocess
from datetime import datetime

GH_TOKEN = os.environ.get("GH_TOKEN", "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")
PROJECT_ID = "PVT_kwHOABOkaM4BVDrk"
STATUS_FIELD_ID = "PVTSSF_lAHOABOkaM4BVDrkzhQiE3c"
STATUS_DONE = "98236657"

GRAPHQL_URL = "https://api.github.com/graphql"


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


def complete_task(item_id):
    """标记任务完成"""
    print(f"\n✅ 标记 GitHub 任务完成...")
    if update_item_status(item_id, STATUS_DONE):
        print("   GitHub 状态已更新为 Done")
        return True
    else:
        print("   GitHub 状态更新失败")
        return False


def main():
    parser = argparse.ArgumentParser(description="执行 GitHub Projects 任务")
    parser.add_argument("--file", type=str, help="任务文件路径")
    parser.add_argument("--item-id", type=str, help="任务ID")
    parser.add_argument("--agent", type=str, help="Agent ID")
    parser.add_argument("--title", type=str, help="任务标题")
    parser.add_argument("--complete", action="store_true", help="仅标记完成")
    args = parser.parse_args()
    
    if args.complete and args.item_id:
        # 仅标记完成
        complete_task(args.item_id)
        return
    
    # 从文件读取任务
    if args.file:
        with open(args.file, "r") as f:
            task = json.load(f)
        
        item_id = task.get("item_id")
        agent_id = task.get("agent_id")
        title = task.get("title")
        task_desc = task.get("task_desc")
    elif args.item_id and args.agent and args.title:
        item_id = args.item_id
        agent_id = args.agent
        title = args.title
        task_desc = f"执行任务: {title}"
    else:
        print("❌ 请提供 --file 或 --item-id + --agent + --title")
        return
    
    print(f"\n{'='*60}")
    print(f"🚀 执行任务")
    print(f"{'='*60}")
    print(f"   任务: {title}")
    print(f"   Agent: {agent_id}")
    print(f"   任务ID: {item_id}")
    print(f"\n{'='*60}")
    print(f"📝 任务描述:")
    print(f"{'='*60}")
    print(task_desc)
    print(f"\n{'='*60}")
    print(f"⚠️  请手动启动 Agent 执行此任务")
    print(f"{'='*60}")
    print(f"\n执行完成后，运行:")
    print(f"   python3 execute_task.py --item-id {item_id} --complete")


if __name__ == "__main__":
    main()
