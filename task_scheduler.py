#!/usr/bin/env python3
"""
GitHub Projects 智能任务调度器（零Token消耗版）

功能：
1. 纯Python轮询，不调用LLM
2. 发现待执行任务时，自动启动Agent
3. Agent执行完成后自动更新GitHub状态
4. 支持子任务检查（所有子任务完成才标记父任务完成）

执行流程：
    轮询 → 发现任务 → 启动Agent → Agent执行 → 回调完成 → 更新状态

使用方法：
    # HEARTBEAT定时调用（每分钟）
    python3 task_scheduler.py
    
    # 手动测试（详细输出）
    python3 task_scheduler.py --verbose

环境变量：
    GH_TOKEN: GitHub Token
    OPENCLAW_API_URL: OpenClaw API地址（默认 http://localhost:3000）
"""

import os
import sys
import json
import time
import argparse
import requests
import subprocess
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

# 导入 CLI 客户端
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from openclaw_cli_client import OpenClawCLIClient

# ============ 配置 ============
GH_TOKEN = os.environ.get("GH_TOKEN", "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")
PROJECT_ID = "PVT_kwHOABOkaM4BVDrk"
STATUS_FIELD_ID = "PVTSSF_lAHOABOkaM4BVDrkzhQiE3c"

STATUS_TODO = "f75ad846"
STATUS_IN_PROGRESS = "47fc9ee4"
STATUS_DONE = "98236657"
STATUS_FAILED = "a2aba7a8"  # Failed 状态ID（需要在GitHub Projects中配置）

# 重试配置
MAX_RETRY_COUNT = 3  # 最大重试次数
RETRY_DELAY_MINUTES = 5  # 重试间隔（分钟）

GRAPHQL_URL = "https://api.github.com/graphql"
STATE_FILE = "/tmp/gh_scheduler_state.json"

# Agent映射表（GitHub用户名/Label → Agent ID）
AGENT_MAP = {
    # Label映射
    "agent:marketing": "marketing",
    "agent:content": "content",
    "agent:dev": "dev",
    "agent:consultant": "consultant",
    "agent:finance": "finance",
    "agent:operations": "operations",
    "agent:ops": "ops",
    "agent:expert": "expert",
    # 用户名映射（可扩展）
    "jiashaoshan": "main",
}


def log(msg: str, verbose: bool = False):
    """日志输出"""
    if verbose or os.environ.get("VERBOSE"):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def graphql_query(query: str, variables: Dict = None) -> Optional[Dict]:
    """执行GraphQL查询"""
    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json"
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    
    try:
        response = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=15)
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


def get_project_items() -> List[Dict]:
    """获取所有任务（包括Issue和DraftIssue）"""
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
                  closed
                  subIssues(first: 50) {{
                    nodes {{
                      id
                      number
                      title
                      state
                      closed
                    }}
                  }}
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
                  ... on ProjectV2ItemFieldTextValue {{
                    field {{ ... on ProjectV2FieldCommon {{ name }} }}
                    text
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


def parse_item_fields(item: Dict) -> Dict[str, Any]:
    """解析任务字段，提取Agent、状态、开始时间等"""
    field_values = item.get("fieldValues", {}).get("nodes", [])
    
    result = {
        "agent": "main",  # 默认分配给主Agent
        "status": "Unknown",
        "start_date": None,
        "custom_fields": {}
    }
    
    for fv in field_values:
        field_name = fv.get("field", {}).get("name", "")
        
        if field_name == "Agent":
            # 优先使用Agent字段
            result["agent"] = fv.get("name", "main")
        elif field_name == "Status":
            option_id = fv.get("optionId", "")
            if option_id == STATUS_TODO:
                result["status"] = "Todo"
            elif option_id == STATUS_IN_PROGRESS:
                result["status"] = "In progress"
            elif option_id == STATUS_DONE:
                result["status"] = "Done"
            elif option_id == STATUS_FAILED:
                result["status"] = "Failed"
        elif field_name == "Start date":
            date_str = fv.get("date", "")
            if date_str:
                # GitHub返回的是本地日期（无时区），添加时区信息
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                result["start_date"] = dt
        else:
            # 收集其他自定义字段
            if "name" in fv:
                result["custom_fields"][field_name] = fv.get("name") or fv.get("text") or fv.get("date")
    
    return result


def detect_agent(item: Dict, fields: Dict) -> str:
    """
    智能检测应该分配给哪个Agent
    优先级：Agent字段 > Labels > 标题关键词 > 正文关键词 > 默认main
    """
    content = item.get("content", {})
    title = content.get("title", "")
    body = content.get("body", "")
    
    # 1. 优先使用Agent字段（如果已设置且不是main）
    if fields.get("agent") and fields["agent"] != "main":
        return fields["agent"]
    
    # 2. 从Labels解析（如果有）
    # 注意：GraphQL查询中需要额外获取labels，这里简化处理
    
    # 3. 从标题关键词匹配
    title_lower = title.lower()
    agent_keywords = {
        "marketing": ["营销", "推广", "获客", "客户拓展", "营销策略", "掘金", "知乎", "bilibili", "引流"],
        "content": ["公众号", "小红书", "文章", "文案", "图文", "内容创作", "写作", "发布"],
        "dev": ["开发", "代码", "脚本", "程序", "架构", "工具", "技能", "github", "api"],
        "consultant": ["调研", "研究", "分析", "报告", "行业", "竞品", "方案"],
        "finance": ["报销", "发票", "财务", "oms", "审批", "预算"],
        "operations": ["客户", "运营", "社群", "平台", "流量"],
        "ops": ["运维", "监控", "系统", "服务器", "告警"],
        "expert": ["专家", "难题", "记录", "记忆"],
    }
    
    for agent, keywords in agent_keywords.items():
        for kw in keywords:
            if kw in title_lower:
                return agent
    
    # 4. 从正文关键词匹配（如果标题没匹配到）
    body_lower = body.lower() if body else ""
    for agent, keywords in agent_keywords.items():
        for kw in keywords:
            if kw in body_lower:
                return agent
    
    # 5. 默认返回main
    return "main"


def update_item_status(item_id: str, status_option_id: str) -> bool:
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
    
    result = graphql_query(mutation, variables)
    return result is not None


def check_subtasks_completed(item: Dict) -> bool:
    """
    检查所有子任务是否已完成
    返回True如果：没有子任务 或 所有子任务都已完成
    """
    content = item.get("content", {})
    sub_issues = content.get("subIssues", {}).get("nodes", [])
    
    if not sub_issues:
        return True  # 没有子任务，直接通过
    
    for sub in sub_issues:
        # 检查子任务状态
        if sub.get("state") == "OPEN" and not sub.get("closed", False):
            return False  # 有未完成的子任务
    
    return True  # 所有子任务都已完成


def load_state() -> Dict:
    """加载调度器状态"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {
        "triggered": {},  # 已触发但未完成的任务
        "completed": [],  # 已完成的任务ID（防重复）
        "failed": {},     # 失败的任务及重试信息
        "last_check": None
    }


def save_state(state: Dict):
    """保存调度器状态"""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def spawn_agent_task(agent: str, title: str, body: str, item_id: str, is_github_task: bool = True):
    """
    启动Agent执行任务
    使用CLI方式异步启动子Agent（不等待完成，避免超时）
    
    Args:
        agent: Agent ID
        title: 任务标题
        body: 任务描述
        item_id: 任务ID（GitHub Projects任务ID或生成的ID）
        is_github_task: 是否是GitHub Projects任务（有对应issue），默认True
    
    注意：子Agent执行完成后需要自己更新GitHub状态（如果是GitHub任务）
    """
    # 根据任务类型构建不同的任务描述
    if is_github_task and item_id.startswith("PVTI_"):
        # GitHub Projects任务 - 需要更新状态
        status_update_instructions = f"""4. 【重要】执行完成后，自己更新GitHub状态：
   - 成功：运行 python3 ~/.openclaw/workspace/skills/github-projects/task_scheduler.py --complete {item_id}
   - 失败：运行 python3 ~/.openclaw/workspace/skills/github-projects/task_scheduler.py --fail {item_id}:失败原因
   - 注意：子Agent必须自己更新GitHub状态，不要依赖主调度器"""
        task_type = "【GitHub Projects 自动任务】"
    else:
        # 直接对话派发的任务 - 不需要更新GitHub状态
        status_update_instructions = f"""4. 【直接对话任务】执行完成后：
   - 不需要更新GitHub状态（无对应issue）
   - 直接进行第5步：群里汇报"""
        task_type = "【直接对话派发任务】"
    
    # 构建任务描述
    task_prompt = f"""{task_type}

任务标题: {title}
任务描述: {body or '(无详细描述)'}
任务ID: {item_id}
分配Agent: {agent}
任务来源: {"GitHub Projects" if is_github_task and item_id.startswith("PVTI_") else "直接对话派发"}

请按以下步骤执行：
1. 读取 ~/.openclaw/workspace/ai-team/{agent}/SKILLS.md
2. 根据任务描述，找到匹配的技能路由规则
3. 调用相应技能完成任务
{status_update_instructions}
5. 使用自己的飞书Bot账号在群里汇报结果（指定accountId="{agent}"）

注意：
- 任务ID: {item_id}
- 如果任务需要创建子任务，请在GitHub上创建子Issue并关联
"""
    
    # 通过 CLI 调用 sessions_spawn（异步启动，不等待完成）
    api_token = os.environ.get("OPENCLAW_API_TOKEN", "aa77e05531fa4da9c57bc54f30c92011eef5b6135df11985")
    
    try:
        client = OpenClawCLIClient(token=api_token)
        # 关键：wait=False 异步启动，避免超时问题
        result = client.spawn_subagent_via_message(
            task=task_prompt,
            agent_id="main",  # 通过 main agent 转发
            label=f"{agent}-github-task",
            wait=False,  # 异步启动，不等待完成
            timeout=10   # 只需要等待确认启动成功
        )
        # 只要状态不是 failed，就认为启动成功
        if result.status.value != "failed":
            log(f"✅ Agent已异步启动: {agent}", True)
            log(f"   任务ID: {item_id}", True)
            return True
        else:
            log(f"⚠️ CLI调用失败: {result.error}", True)
            return False
    except Exception as e:
        log(f"⚠️ CLI调用异常: {e}", True)
        return False


def mark_task_complete(item_id: str) -> bool:
    """
    标记任务完成
    检查子任务状态，只有所有子任务完成才更新父任务状态
    """
    log(f"\n🏁 标记任务完成: {item_id}")
    
    # 获取最新任务状态
    items = get_project_items()
    target_item = None
    
    for item in items:
        if item.get("id") == item_id:
            target_item = item
            break
    
    if not target_item:
        log(f"❌ 未找到任务: {item_id}")
        return False
    
    # 检查子任务
    if not check_subtasks_completed(target_item):
        log(f"⏳ 任务有未完成的子任务，暂不标记完成")
        # 可以在这里添加评论提醒
        return False
    
    # 更新状态为Done
    if update_item_status(item_id, STATUS_DONE):
        log(f"✅ 任务已标记为 Done")
        
        # 更新状态文件
        state = load_state()
        if item_id in state["triggered"]:
            state["completed"].append(item_id)
            del state["triggered"][item_id]
        # 清理失败记录
        if item_id in state.get("failed", {}):
            del state["failed"][item_id]
        save_state(state)
        
        return True
    else:
        log(f"❌ 更新状态失败")
        return False


def mark_task_failed(item_id: str, reason: str = "") -> bool:
    """
    标记任务失败
    更新GitHub状态为Failed，并记录重试信息
    """
    log(f"\n❌ 标记任务失败: {item_id}")
    if reason:
        log(f"   原因: {reason}")
    
    # 更新状态为Failed
    if update_item_status(item_id, STATUS_FAILED):
        log(f"   ✅ GitHub状态已更新: Failed")
        
        # 更新状态文件，记录失败信息
        state = load_state()
        if item_id not in state.get("failed", {}):
            state["failed"][item_id] = {
                "retry_count": 0,
                "first_failed_at": datetime.now().isoformat(),
                "last_failed_at": datetime.now().isoformat(),
                "reason": reason
            }
        else:
            state["failed"][item_id]["retry_count"] += 1
            state["failed"][item_id]["last_failed_at"] = datetime.now().isoformat()
            state["failed"][item_id]["reason"] = reason
        
        # 从triggered中移除
        if item_id in state.get("triggered", {}):
            del state["triggered"][item_id]
        
        save_state(state)
        return True
    else:
        log(f"   ❌ 更新GitHub状态失败")
        return False


def should_retry_task(item_id: str) -> bool:
    """
    判断任务是否应该重试
    检查重试次数和间隔时间
    """
    state = load_state()
    failed_info = state.get("failed", {}).get(item_id)
    
    if not failed_info:
        return False
    
    retry_count = failed_info.get("retry_count", 0)
    last_failed = failed_info.get("last_failed_at")
    
    # 检查重试次数
    if retry_count >= MAX_RETRY_COUNT:
        log(f"   ⚠️ 任务 {item_id} 已达到最大重试次数 ({MAX_RETRY_COUNT})，不再重试")
        return False
    
    # 检查重试间隔
    if last_failed:
        last_failed_time = datetime.fromisoformat(last_failed)
        minutes_since_fail = (datetime.now() - last_failed_time).total_seconds() / 60
        if minutes_since_fail < RETRY_DELAY_MINUTES:
            log(f"   ⏳ 任务 {item_id} 还需等待 {RETRY_DELAY_MINUTES - minutes_since_fail:.1f} 分钟后重试")
            return False
    
    return True


def retry_task(item_id: str, title: str, body: str, agent: str) -> bool:
    """
    重试失败的任务
    """
    log(f"\n🔄 重试任务: {title}")
    log(f"   分配给Agent: {agent}")
    
    # 1. 更新GitHub状态为In progress
    if update_item_status(item_id, STATUS_IN_PROGRESS):
        log(f"   ✅ GitHub状态已更新: In progress")
    else:
        log(f"   ❌ GitHub状态更新失败")
        return False
    
    # 2. 启动Agent
    if spawn_agent_task(agent, title, body, item_id):
        # 更新状态文件
        state = load_state()
        state["triggered"][item_id] = {
            "title": title,
            "agent": agent,
            "triggered_at": datetime.now().isoformat(),
            "is_retry": True
        }
        save_state(state)
        log(f"   ✅ Agent已启动（重试）")
        return True
    else:
        log(f"   ❌ Agent启动失败")
        return False


def process_tasks(verbose: bool = False) -> int:
    """
    处理所有任务
    返回触发的任务数量（包括新任务和重试任务）
    """
    log("=" * 60, verbose)
    log("🤖 GitHub Projects 任务调度器", verbose)
    log("=" * 60, verbose)
    
    # 获取所有任务
    items = get_project_items()
    log(f"📊 获取到 {len(items)} 个任务", verbose)
    
    if not items:
        return 0
    
    # 加载状态
    state = load_state()
    now = datetime.now(timezone.utc)
    triggered_count = 0
    
    for item in items:
        content = item.get("content", {})
        if not content:
            continue
        
        item_id = item.get("id", "")
        title = content.get("title", "")
        body = content.get("body", "")
        
        # 解析字段
        fields = parse_item_fields(item)
        
        # 智能检测Agent
        agent = detect_agent(item, fields)
        
        log(f"\n📋 {title}", verbose)
        log(f"   状态: {fields['status']} | Agent: {agent} | 开始时间: {fields.get('start_date')}", verbose)
        
        # 处理 Failed 状态的任务 - 检查是否需要重试
        if fields["status"] == "Failed":
            log(f"   ⚠️ 任务处于 Failed 状态", verbose)
            if should_retry_task(item_id):
                if retry_task(item_id, title, body, agent):
                    triggered_count += 1
            else:
                log(f"   ⏭️ 跳过重试", verbose)
            continue
        
        # 检查是否应该触发（Todo 状态）
        if fields["status"] != "Todo":
            continue
        
        # 如果没有开始时间，默认为今天（立即执行）
        if not fields.get("start_date"):
            fields["start_date"] = now
            log(f"   ⏰ 未设置开始时间，默认今天执行", verbose)
        
        # 检查是否已经触发过
        if item_id in state.get("triggered", {}):
            log(f"   ⏳ 已触发，等待完成", verbose)
            continue
        
        if item_id in state.get("completed", []):
            log(f"   ✅ 已完成", verbose)
            continue
        
        # 触发任务
        log(f"\n🚀 触发任务: {title}", True)
        log(f"   分配给Agent: {agent}", True)
        
        # 1. 更新GitHub状态为In progress
        if update_item_status(item_id, STATUS_IN_PROGRESS):
            log(f"   ✅ GitHub状态已更新: In progress", True)
        else:
            log(f"   ❌ GitHub状态更新失败，跳过", True)
            continue
        
        # 2. 启动Agent
        if spawn_agent_task(agent, title, body, item_id):
            # 记录已触发
            state["triggered"][item_id] = {
                "title": title,
                "agent": agent,
                "triggered_at": datetime.now().isoformat()
            }
            triggered_count += 1
            log(f"   ✅ Agent已启动", True)
        else:
            log(f"   ❌ Agent启动失败", True)
    
    # 保存状态
    state["last_check"] = datetime.now().isoformat()
    save_state(state)
    
    log(f"\n{'='*60}", verbose)
    log(f"✅ 本次触发 {triggered_count} 个任务", verbose)
    log(f"{'='*60}", verbose)
    
    return triggered_count


def main():
    parser = argparse.ArgumentParser(description="GitHub Projects 智能任务调度器")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--complete", metavar="ITEM_ID", help="标记指定任务完成")
    parser.add_argument("--fail", metavar="ITEM_ID", help="标记指定任务失败（格式: ITEM_ID:失败原因）")
    parser.add_argument("--retry", metavar="ITEM_ID", help="手动重试指定失败任务")
    parser.add_argument("--once", action="store_true", help="只执行一次")
    parser.add_argument("--interval", type=int, default=1, help="轮询间隔(分钟)")
    args = parser.parse_args()
    
    # 处理标记完成
    if args.complete:
        success = mark_task_complete(args.complete)
        sys.exit(0 if success else 1)
    
    # 处理标记失败
    if args.fail:
        parts = args.fail.split(":", 1)
        item_id = parts[0]
        reason = parts[1] if len(parts) > 1 else "Agent执行失败"
        success = mark_task_failed(item_id, reason)
        sys.exit(0 if success else 1)
    
    # 处理手动重试
    if args.retry:
        # 获取任务信息
        state = load_state()
        failed_info = state.get("failed", {}).get(args.retry)
        if failed_info:
            # 这里需要获取任务详细信息，简化处理
            log(f"🔄 手动重试任务: {args.retry}")
            # 实际实现需要查询GitHub获取任务详情
            log(f"   请通过GitHub Projects界面将任务状态改为Todo后重新触发")
        else:
            log(f"❌ 未找到失败任务记录: {args.retry}")
        sys.exit(0)
    
    # 持续轮询模式
    while True:
        try:
            process_tasks(args.verbose)
        except Exception as e:
            log(f"❌ 错误: {e}", True)
        
        if args.once:
            break
        
        # 等待下一轮
        time.sleep(args.interval * 60)


if __name__ == "__main__":
    main()
