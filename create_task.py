#!/usr/bin/env python3
"""
GitHub Projects 任务创建工具

功能：
1. 在指定 GitHub Project 中创建任务
2. 自动设置标题、描述、Agent、状态字段
3. 支持自定义开始时间

使用方法：
    # 创建默认任务（市场营销-热点新闻）
    python3 create_task.py
    
    # 创建指定 Agent 的任务
    python3 create_task.py --agent marketing --title "【市场营销】获取最新的热点新闻"
    
    # 创建带自定义描述的任务
    python3 create_task.py --agent dev --title "【开发】开发新功能" --desc "详细描述..."
    
    # 指定开始时间
    python3 create_task.py --start-date 2026-04-24

环境变量：
    GH_TOKEN: GitHub Token（必填）
    GH_PROJECT_ID: GitHub Project ID（可选，默认使用配置）
"""

import os
import sys
import json
import argparse
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

# ============ 配置加载 ============
CONFIG_FILE = Path.home() / ".openclaw" / "github-projects-config.json"

def load_config():
    """加载配置，优先级：环境变量 > 配置文件 > 默认值"""
    config = {
        "gh_token": "",
        "project_id": "PVT_kwHOABOkaM4BVDrk",
        "status_field_id": "PVTSSF_lAHOABOkaM4BVDrkzhQiE3c",
        "agent_field_id": "PVTSSF_lAHOABOkaM4BVDrkzhQl13Y",
        "start_date_field_id": "PVTF_lAHOABOkaM4BVDrkzhQiE-c",
    }
    
    # 1. 从配置文件读取
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                file_config = json.load(f)
                for key, value in file_config.items():
                    if key in config and value:
                        config[key] = value
        except Exception as e:
            print(f"⚠️ 配置文件读取失败: {e}")
    
    # 2. 从环境变量读取（最高优先级）
    env_mappings = {
        "gh_token": "GH_TOKEN",
        "project_id": "GH_PROJECT_ID",
    }
    for config_key, env_key in env_mappings.items():
        env_value = os.environ.get(env_key, "")
        if env_value:
            config[config_key] = env_value
    
    return config

CONFIG = load_config()

# ============ 配置项 ============
GH_TOKEN = CONFIG["gh_token"]
PROJECT_ID = CONFIG["project_id"]
STATUS_FIELD_ID = CONFIG["status_field_id"]
AGENT_FIELD_ID = CONFIG["agent_field_id"]
START_DATE_FIELD_ID = CONFIG["start_date_field_id"]

# Agent 选项映射
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

# 状态选项
STATUS_TODO = "f75ad846"

GRAPHQL_URL = "https://api.github.com/graphql"


def graphql_query(query: str, variables: Dict = None) -> Optional[Dict]:
    """执行 GraphQL 查询"""
    if not GH_TOKEN:
        print("❌ 错误: GH_TOKEN 未设置")
        return None
    
    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json"
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    
    try:
        response = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            print(f"❌ GraphQL 错误: {data['errors']}")
            return None
        return data.get("data")
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return None


def create_draft_issue(title: str, body: str) -> Optional[str]:
    """创建 Draft Issue"""
    mutation = """
    mutation($projectId: ID!, $title: String!, $body: String) {
        addProjectV2DraftIssue(
            input: {
                projectId: $projectId
                title: $title
                body: $body
            }
        ) {
            projectItem {
                id
            }
        }
    }
    """
    
    result = graphql_query(mutation, {
        "projectId": PROJECT_ID,
        "title": title,
        "body": body
    })
    
    if result:
        item_id = result.get("addProjectV2DraftIssue", {}).get("projectItem", {}).get("id")
        return item_id
    return None


def update_item_field(item_id: str, field_id: str, value: str) -> bool:
    """更新任务字段"""
    mutation = """
    mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $value: String!) {
        updateProjectV2ItemFieldValue(
            input: {
                projectId: $projectId
                itemId: $itemId
                fieldId: $fieldId
                value: { singleSelectOptionId: $value }
            }
        ) {
            clientMutationId
        }
    }
    """
    
    result = graphql_query(mutation, {
        "projectId": PROJECT_ID,
        "itemId": item_id,
        "fieldId": field_id,
        "value": value
    })
    
    return result is not None


def update_start_date(item_id: str, date_str: str) -> bool:
    """更新开始时间"""
    mutation = """
    mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $date: Date!) {
        updateProjectV2ItemFieldValue(
            input: {
                projectId: $projectId
                itemId: $itemId
                fieldId: $fieldId
                value: { date: $date }
            }
        ) {
            clientMutationId
        }
    }
    """
    
    result = graphql_query(mutation, {
        "projectId": PROJECT_ID,
        "itemId": item_id,
        "fieldId": START_DATE_FIELD_ID,
        "date": date_str
    })
    
    return result is not None


def get_default_description(agent: str) -> str:
    """获取默认任务描述"""
    templates = {
        "marketing": """## 任务描述
获取最新的热点新闻

## 获取渠道
1. 知乎
2. 掘金
3. 小红书

## 获取时间范围
近2天

## 关注领域
- 金融
- 科技
- 军事

## 输出要求
- 整理热点话题列表
- 分析热度趋势
- 生成简报""",
        
        "content": """## 任务描述
创作内容

## 内容类型
- [ ] 小红书文案
- [ ] 公众号文章
- [ ] 知乎回答

## 主题方向
待补充...

## 输出要求
- 符合平台风格
- 包含 emoji 和 hashtag
- 吸引目标用户""",
        
        "dev": """## 任务描述
开发任务

## 功能需求
待补充...

## 技术栈
- Python / Node.js
- 其他...

## 验收标准
- [ ] 功能实现
- [ ] 代码测试
- [ ] 文档更新""",
        
        "consultant": """## 任务描述
调研分析

## 调研目标
待补充...

## 分析方法
- 数据收集
- 竞品分析
- 趋势研究

## 输出要求
- 调研报告
- 数据可视化
- 结论建议""",
        
        "finance": """## 任务描述
财务处理

## 任务类型
- [ ] 报销处理
- [ ] 发票整理
- [ ] OMS填报
- [ ] 财务核算

## 具体要求
待补充...

## 截止时间
待补充...""",
        
        "operations": """## 任务描述
客户运营

## 运营目标
- 客户拓展
- 平台监控
- 社群管理

## 具体任务
待补充...

## 输出要求
- 运营数据
- 客户反馈
- 优化建议""",
        
        "ops": """## 任务描述
运维监控

## 监控项
- 系统状态
- 服务健康
- 资源使用

## 检查内容
- [ ] CPU/内存
- [ ] 磁盘空间
- [ ] 网络连接
- [ ] 日志检查

## 异常处理
如有异常，立即告警并记录""",
    }
    
    return templates.get(agent, "## 任务描述\n待补充...")


def main():
    parser = argparse.ArgumentParser(description="GitHub Projects 任务创建工具")
    parser.add_argument("--agent", default="marketing",
                      choices=list(AGENT_OPTIONS.keys()),
                      help="指定 Agent (默认: marketing)")
    parser.add_argument("--title", type=str,
                      help="任务标题 (默认: 【agent】获取最新的热点新闻)")
    parser.add_argument("--desc", type=str,
                      help="任务描述 (默认使用模板)")
    parser.add_argument("--start-date", type=str,
                      help="开始时间 (格式: YYYY-MM-DD，默认: 今天)")
    parser.add_argument("--status", default="todo",
                      choices=["todo", "in_progress", "done"],
                      help="任务状态 (默认: todo)")
    
    args = parser.parse_args()
    
    # 检查 GH_TOKEN
    if not GH_TOKEN:
        print("❌ 错误: GH_TOKEN 未设置")
        print("请设置环境变量: export GH_TOKEN='your_token'")
        sys.exit(1)
    
    # 准备任务数据
    agent_name = args.agent
    agent_id = AGENT_OPTIONS[agent_name]
    
    # 标题
    if args.title:
        title = args.title
    else:
        title = f"【{agent_name}】获取最新的热点新闻"
    
    # 描述
    if args.desc:
        body = args.desc
    else:
        body = get_default_description(agent_name)
    
    # 开始时间
    if args.start_date:
        start_date = args.start_date
    else:
        start_date = datetime.now().strftime("%Y-%m-%d")
    
    print(f"📝 创建任务...")
    print(f"   Agent: {agent_name}")
    print(f"   标题: {title}")
    print(f"   开始时间: {start_date}")
    
    # 创建 Draft Issue
    item_id = create_draft_issue(title, body)
    if not item_id:
        print("❌ 创建任务失败")
        sys.exit(1)
    
    print(f"✅ 任务创建成功: {item_id}")
    
    # 更新 Agent 字段
    if update_item_field(item_id, AGENT_FIELD_ID, agent_id):
        print(f"✅ Agent 字段已设置: {agent_name}")
    else:
        print(f"⚠️ Agent 字段设置失败")
    
    # 更新状态为 Todo
    if update_item_field(item_id, STATUS_FIELD_ID, STATUS_TODO):
        print(f"✅ 状态已设置: Todo")
    else:
        print(f"⚠️ 状态设置失败")
    
    # 更新开始时间
    if update_start_date(item_id, start_date):
        print(f"✅ 开始时间已设置: {start_date}")
    else:
        print(f"⚠️ 开始时间设置失败")
    
    print(f"\n🎉 任务创建完成!")
    print(f"   任务ID: {item_id}")
    print(f"   调度器将在 {start_date} 自动执行")


if __name__ == "__main__":
    main()
