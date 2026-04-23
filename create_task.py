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
# 配置文件路径（项目目录）
CONFIG_FILE = Path(__file__).parent / "config.json"

def load_config():
    """加载配置，只从配置文件读取"""
    if not CONFIG_FILE.exists():
        print(f"❌ 配置文件不存在: {CONFIG_FILE}")
        sys.exit(1)
    
    try:
        with open(CONFIG_FILE) as f:
            config = json.load(f)
    except Exception as e:
        print(f"❌ 配置文件读取失败: {e}")
        sys.exit(1)
    
    return config

CONFIG = load_config()

# ============ 配置项 ============
GH_TOKEN = CONFIG["gh_token"]
PROJECT_ID = CONFIG["project_id"]

# Agent 选项映射（运行时自动填充）
AGENT_OPTIONS = {}
AGENT_NAMES = ["marketing", "content", "dev", "consultant", "finance", "operations", "ops", "hermes", "main"]

# 字段 ID（运行时自动填充）
STATUS_FIELD_ID = None
AGENT_FIELD_ID = None
START_DATE_FIELD_ID = None
STATUS_TODO = None

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


def resolve_project_fields():
    """
    自动获取项目的字段 ID 和选项 ID（根据字段名称），
    取代硬编码的字段 ID 配置。
    """
    global STATUS_FIELD_ID, AGENT_FIELD_ID, START_DATE_FIELD_ID, STATUS_TODO
    global AGENT_OPTIONS
    
    query = """
    query($projectId: ID!) {
        node(id: $projectId) {
            ... on ProjectV2 {
                fields(first: 20) {
                    nodes {
                        __typename
                        ... on ProjectV2FieldCommon {
                            name
                            id
                        }
                        ... on ProjectV2SingleSelectField {
                            name
                            id
                            options {
                                id
                                name
                            }
                        }
                    }
                }
            }
        }
    }
    """
    
    result = graphql_query(query, {"projectId": PROJECT_ID})
    if not result:
        print("⚠️ 无法获取项目字段信息")
        return False
    
    fields = result.get("node", {}).get("fields", {}).get("nodes", [])
    
    for field in fields:
        field_name = field.get("name", "")
        
        if field_name == "Status":
            STATUS_FIELD_ID = field.get("id")
            for opt in field.get("options", []):
                if opt.get("name") == "Todo":
                    STATUS_TODO = opt.get("id")
        
        elif field_name == "Agent":
            AGENT_FIELD_ID = field.get("id")
            for opt in field.get("options", []):
                opt_name = opt.get("name", "")
                if opt_name in AGENT_NAMES:
                    AGENT_OPTIONS[opt_name] = opt.get("id")
        
        elif field_name == "Start date":
            START_DATE_FIELD_ID = field.get("id")
    
    missing = []
    if not STATUS_FIELD_ID or not STATUS_TODO: missing.append("Status")
    if not AGENT_FIELD_ID or not AGENT_OPTIONS: missing.append("Agent")
    if not START_DATE_FIELD_ID: missing.append("Start date")
    
    if missing:
        print(f"⚠️ 字段解析不完整，缺少: {', '.join(missing)}")
        return False
    
    print(f"✅ 已自动获取字段：Status={STATUS_FIELD_ID[:12]}... Agent选项={len(AGENT_OPTIONS)}个")
    return True


def get_repository_id() -> Optional[str]:
    """获取默认仓库 ID"""
    # 从 PROJECT_ID 解析仓库信息，或者使用默认仓库
    # 这里假设使用用户的默认仓库，可以通过环境变量配置
    repo_owner = os.environ.get("GH_REPO_OWNER", "jiashaoshan")
    repo_name = os.environ.get("GH_REPO_NAME", "openclaw-github-projects-scheduler")
    
    query = """
    query($owner: String!, $name: String!) {
        repository(owner: $owner, name: $name) {
            id
        }
    }
    """
    
    result = graphql_query(query, {"owner": repo_owner, "name": repo_name})
    if result:
        return result.get("repository", {}).get("id")
    return None


def get_repository_id() -> Optional[str]:
    """获取默认仓库 ID"""
    repo_owner = os.environ.get("GH_REPO_OWNER", "jiashaoshan")
    repo_name = os.environ.get("GH_REPO_NAME", "openclaw-github-projects-scheduler")
    
    query = """
    query($owner: String!, $name: String!) {
        repository(owner: $owner, name: $name) {
            id
        }
    }
    """
    
    result = graphql_query(query, {"owner": repo_owner, "name": repo_name})
    if result:
        return result.get("repository", {}).get("id")
    return None


def create_issue(title: str, body: str) -> Optional[str]:
    """创建正式 Issue 并添加到指定 Project"""
    # 1. 先创建 Issue
    repository_id = get_repository_id()
    if not repository_id:
        print("❌ 无法获取仓库 ID")
        return None
    
    mutation = """
    mutation($repositoryId: ID!, $title: String!, $body: String) {
        createIssue(
            input: {
                repositoryId: $repositoryId
                title: $title
                body: $body
            }
        ) {
            issue {
                id
                number
                url
            }
        }
    }
    """
    
    result = graphql_query(mutation, {
        "repositoryId": repository_id,
        "title": title,
        "body": body
    })
    
    if not result:
        return None
    
    issue = result.get("createIssue", {}).get("issue", {})
    issue_id = issue.get("id")
    issue_number = issue.get("number")
    issue_url = issue.get("url")
    print(f"✅ Issue #{issue_number} 已创建")
    
    # 2. 添加到指定 Project
    mutation2 = """
    mutation($projectId: ID!, $contentId: ID!) {
        addProjectV2ItemById(
            input: {
                projectId: $projectId
                contentId: $contentId
            }
        ) {
            item {
                id
            }
        }
    }
    """
    
    result2 = graphql_query(mutation2, {
        "projectId": PROJECT_ID,
        "contentId": issue_id
    })
    
    if result2:
        item_id = result2.get("addProjectV2ItemById", {}).get("item", {}).get("id")
        print(f"✅ 已添加到项目: {item_id}")
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
    
    # 初始化：自动获取项目字段配置
    print("正在解析项目字段配置...")
    if PROJECT_ID:
        resolve_project_fields()
    else:
        print("⚠️ 未配置 PROJECT_ID")
    
    # 检查字段是否已成功获取
    if not AGENT_OPTIONS:
        print("❌ 无法获取 Agent 字段选项，请检查 GH_TOKEN 和 project_id")
        sys.exit(1)
    
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
    
    # 创建正式 Issue（状态为 Open）
    item_id = create_issue(title, body)
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
