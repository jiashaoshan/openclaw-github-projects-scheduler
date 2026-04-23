#!/usr/bin/env python3
"""
GitHub Projects 实时触发处理器

功能：
1. 接收 GitHub Webhook 或手动触发
2. 根据 "Agent" 字段自动分发任务
3. Agent 执行中自动更新状态为 "In progress"
4. Agent 完成后自动更新状态为 "Done"

使用方法：
    # 作为 Webhook 接收器
    python3 webhook_handler.py --server --port 8080
    
    # 手动触发单个任务
    python3 webhook_handler.py --item-id PVTI_xxx
    
    # 监听模式（轮询，仅用于测试）
    python3 webhook_handler.py --watch --interval 10

环境变量：
    GH_TOKEN: GitHub Personal Access Token
"""

import os
import sys
import json
import argparse
import requests
import subprocess
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============ 配置 ============
GH_TOKEN = os.environ.get("GH_TOKEN", "")
PROJECT_ID = "PVT_kwHOABOkaM4BVDrk"
STATUS_FIELD_ID = "PVTSSF_lAHOABOkaM4BVDrkzhQiE3c"
AGENT_FIELD_ID = "PVTSSF_lAHOABOkaM4BVDrkzhQl13Y"

# Status Option IDs
STATUS_TODO = "f75ad846"
STATUS_IN_PROGRESS = "47fc9ee4"
STATUS_DONE = "98236657"

GRAPHQL_URL = "https://api.github.com/graphql"

# ============ GraphQL 操作 ============

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


def get_item_details(item_id):
    """获取任务详情"""
    query = """
    query($itemId: ID!) {
      node(id: $itemId) {
        ... on ProjectV2Item {
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
          fieldValues(first: 20) {
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
    """
    
    data = graphql_query(query, {"itemId": item_id})
    if not data:
        return None
    
    return data.get("node")


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


def parse_item_agent(item):
    """解析任务分配的 Agent"""
    field_values = item.get("fieldValues", {}).get("nodes", [])
    
    for fv in field_values:
        field_name = fv.get("field", {}).get("name", "")
        if field_name == "Agent":
            return fv.get("name", "main")
    
    return "main"


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


# ============ Agent 执行 ============

def execute_agent_task(item):
    """执行任务并管理状态"""
    content = item.get("content", {})
    item_id = item.get("id", "")
    
    title = content.get("title", "")
    body = content.get("body", "")
    agent = parse_item_agent(item)
    
    print(f"\n{'='*60}")
    print(f"🚀 开始执行任务")
    print(f"{'='*60}")
    print(f"   标题: {title}")
    print(f"   Agent: {agent}")
    print(f"   任务ID: {item_id}")
    
    # Step 1: 更新状态为 "In progress"
    print(f"\n⏳ 更新状态: In progress...")
    if update_item_status(item_id, STATUS_IN_PROGRESS):
        print("   ✅ 状态已更新")
    else:
        print("   ❌ 状态更新失败")
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
- 执行完成后，系统会自动将任务状态更新为 "Done"
- 如有执行日志或输出文件，请说明路径
"""
    
    # Step 3: 启动 Agent（使用 sessions_spawn）
    print(f"\n🤖 启动 Agent: {agent}")
    print(f"   任务已准备，等待 Agent 执行...")
    
    # 保存任务信息供外部调用
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
    
    print(f"   📄 任务文件: {task_file}")
    
    # 这里返回任务信息，由调用者决定是否启动 Agent
    return {
        "item_id": item_id,
        "agent_id": agent,
        "title": title,
        "task_file": task_file,
        "task_desc": task_desc
    }


def complete_task(item_id, result_summary=""):
    """标记任务完成"""
    print(f"\n✅ 标记任务完成...")
    if update_item_status(item_id, STATUS_DONE):
        print("   状态已更新为 Done")
        
        # 添加评论（如果有关联的 Issue）
        # TODO: 添加完成评论
        
        return True
    else:
        print("   状态更新失败")
        return False


# ============ Webhook 处理 ============

class WebhookHandler(BaseHTTPRequestHandler):
    """GitHub Webhook 处理器"""
    
    def do_POST(self):
        """处理 POST 请求"""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            payload = json.loads(post_data)
            
            # 处理 Projects V2 事件
            action = payload.get("action", "")
            
            if action in ["edited", "created"]:
                # 检查是否是状态变更
                changes = payload.get("changes", {})
                
                # 获取 item 信息
                item = payload.get("projects_v2_item", {})
                item_id = item.get("id", "")
                
                if item_id:
                    print(f"\n📥 收到 Webhook: {action}")
                    print(f"   Item ID: {item_id}")
                    
                    # 获取完整任务信息
                    item_details = get_item_details(item_id)
                    if item_details:
                        status = parse_item_status(item_details)
                        
                        # 只在状态变为 "In progress" 时触发
                        if status == "In progress":
                            result = execute_agent_task(item_details)
                            if result:
                                self.send_response(200)
                                self.send_header('Content-Type', 'application/json')
                                self.end_headers()
                                self.wfile.write(json.dumps({
                                    "status": "triggered",
                                    "agent": result["agent_id"],
                                    "task_file": result["task_file"]
                                }).encode())
                                return
            
            self.send_response(200)
            self.end_headers()
            
        except Exception as e:
            print(f"❌ Webhook 处理错误: {e}")
            self.send_response(500)
            self.end_headers()
    
    def log_message(self, format, *args):
        """自定义日志"""
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {args[0]}")


def start_webhook_server(port=8080):
    """启动 Webhook 服务器"""
    server = HTTPServer(('0.0.0.0', port), WebhookHandler)
    print(f"\n🌐 Webhook 服务器已启动")
    print(f"   监听地址: http://0.0.0.0:{port}")
    print(f"   在 GitHub Project 设置 Webhook 指向此地址")
    print(f"   按 Ctrl+C 停止\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n🛑 服务器已停止")


# ============ 主函数 ============

def main():
    parser = argparse.ArgumentParser(description="GitHub Projects 实时触发处理器")
    parser.add_argument("--server", action="store_true", help="启动 Webhook 服务器")
    parser.add_argument("--port", type=int, default=8080, help="服务器端口")
    parser.add_argument("--item-id", type=str, help="手动触发指定任务")
    parser.add_argument("--complete", type=str, help="标记指定任务为完成")
    parser.add_argument("--watch", action="store_true", help="监听模式（轮询）")
    parser.add_argument("--interval", type=int, default=10, help="轮询间隔(秒)")
    args = parser.parse_args()
    
    if args.server:
        start_webhook_server(args.port)
    
    elif args.item_id:
        # 手动触发单个任务
        print(f"📋 获取任务详情: {args.item_id}")
        item = get_item_details(args.item_id)
        
        if not item:
            print("❌ 任务不存在")
            return
        
        status = parse_item_status(item)
        print(f"   当前状态: {status}")
        
        if status == "In progress":
            result = execute_agent_task(item)
            if result:
                print(f"\n{'='*60}")
                print("📝 任务已分发，请手动启动 Agent:")
                print(f"{'='*60}")
                print(f"   Agent: {result['agent_id']}")
                print(f"   任务文件: {result['task_file']}")
                print(f"\n执行命令:")
                print(f"   sessions_spawn --task-file {result['task_file']}")
        else:
            print(f"   任务状态不是 'In progress'，跳过")
    
    elif args.complete:
        # 标记任务完成
        complete_task(args.complete)
    
    elif args.watch:
        # 监听模式（仅用于测试）
        print(f"👀 监听模式启动，间隔 {args.interval} 秒")
        print("   按 Ctrl+C 停止\n")
        
        try:
            while True:
                # 这里可以添加轮询逻辑
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n🛑 监听已停止")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
