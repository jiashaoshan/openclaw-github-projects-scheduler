#!/usr/bin/env python3
"""
飞书消息监听服务器

功能：
1. 接收飞书群消息（来自 GitHub Actions）
2. 解析任务信息
3. 触发对应 Agent 执行
4. 执行完成后回复飞书消息

使用方法：
    python3 feishu-webhook-server.py

环境变量：
    FEISHU_APP_ID: 飞书应用 ID
    FEISHU_APP_SECRET: 飞书应用密钥
    GH_TOKEN: GitHub Token
"""

import os
import json
import re
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# ============ 配置 ============
GH_TOKEN = os.environ.get("GH_TOKEN", "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")
PROJECT_ID = "PVT_kwHOABOkaM4BVDrk"
STATUS_FIELD_ID = "PVTSSF_lAHOABOkaM4BVDrkzhQiE3c"
STATUS_IN_PROGRESS = "47fc9ee4"
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


class FeishuWebhookHandler(BaseHTTPRequestHandler):
    """飞书 Webhook 处理器"""
    
    def do_POST(self):
        """处理飞书消息"""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            payload = json.loads(post_data)
            
            # 解析飞书消息
            msg_type = payload.get("header", {}).get("event_type", "")
            
            if msg_type == "im.message.receive_v1":
                message = payload.get("event", {}).get("message", {})
                content = json.loads(message.get("content", "{}"))
                
                # 检查是否是 GitHub Projects 触发消息
                text = content.get("text", "")
                
                # 解析任务信息
                # 格式: 🚀 GitHub Projects 任务触发\n**任务:** xxx\n**Agent:** xxx\n**任务ID:** xxx
                if "GitHub Projects 任务触发" in text:
                    print(f"\n{'='*60}")
                    print(f"📥 收到 GitHub Projects 触发")
                    print(f"{'='*60}")
                    
                    # 解析任务信息
                    title_match = re.search(r'\*\*任务:\*\* (.+?)\n', text)
                    agent_match = re.search(r'\*\*Agent:\*\* (.+?)\n', text)
                    item_id_match = re.search(r'\*\*任务ID:\*\* (.+?)\n', text)
                    
                    if title_match and agent_match and item_id_match:
                        title = title_match.group(1).strip()
                        agent = agent_match.group(1).strip()
                        item_id = item_id_match.group(1).strip()
                        
                        print(f"   任务: {title}")
                        print(f"   Agent: {agent}")
                        print(f"   任务ID: {item_id}")
                        
                        # Step 1: 更新状态为 In progress
                        print(f"\n⏳ 更新 GitHub 状态: In progress...")
                        if update_item_status(item_id, STATUS_IN_PROGRESS):
                            print("   ✅ GitHub 状态已更新")
                        else:
                            print("   ❌ GitHub 状态更新失败")
                        
                        # Step 2: 生成任务文件
                        task_file = f"/tmp/gh_project_task_{item_id.replace('/', '_')}.json"
                        task_desc = f"""【GitHub Projects 任务执行】

任务ID: {item_id}
标题: {title}
分配Agent: {agent}

请执行以下步骤：
1. 读取 ~/.openclaw/workspace/ai-team/{agent}/SKILLS.md
2. 根据任务描述，找到匹配的技能路由规则
3. 调用相应技能完成任务
4. 返回执行结果摘要

注意：
- 如果任务描述不够具体，请先向用户确认
- 执行完成后，系统会自动将 GitHub 状态更新为 "Done"
"""
                        
                        with open(task_file, "w") as f:
                            json.dump({
                                "item_id": item_id,
                                "agent_id": agent,
                                "title": title,
                                "task_desc": task_desc,
                                "status": "in_progress",
                                "created_at": datetime.now().isoformat()
                            }, f, ensure_ascii=False, indent=2)
                        
                        print(f"\n📄 任务文件: {task_file}")
                        print(f"\n🚀 任务已准备，等待手动启动 Agent:")
                        print(f"   Agent: {agent}")
                        print(f"\n请运行:")
                        print(f"   python3 ~/.openclaw/workspace/skills/github-projects/execute_task.py --file {task_file}")
                        
                        # 回复飞书消息
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "code": 0,
                            "msg": "success"
                        }).encode())
                        return
            
            self.send_response(200)
            self.end_headers()
            
        except Exception as e:
            print(f"❌ 处理错误: {e}")
            self.send_response(500)
            self.end_headers()
    
    def log_message(self, format, *args):
        """自定义日志"""
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {args[0]}")


def start_server(port=8080):
    """启动服务器"""
    server = HTTPServer(('0.0.0.0', port), FeishuWebhookHandler)
    print(f"\n🌐 飞书 Webhook 服务器已启动")
    print(f"   监听地址: http://0.0.0.0:{port}")
    print(f"   按 Ctrl+C 停止\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n🛑 服务器已停止")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    
    start_server(args.port)
