#!/usr/bin/env python3
"""
GitHub Projects Agent 任务执行器

这个脚本由子Agent调用，用于：
1. 读取任务详情
2. 执行对应的技能
3. 完成任务后自动更新GitHub状态

使用方法（在子Agent内部）：
    python3 ~/.openclaw/workspace/skills/github-projects/agent_runner.py \
        --agent marketing \
        --task "写一篇小红书文案" \
        --item-id PVTI_xxx

或从任务文件执行：
    python3 ~/.openclaw/workspace/skills/github-projects/agent_runner.py \
        --file /tmp/gh_task_xxx.json
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path

# 添加技能目录到路径
SKILLS_DIR = Path.home() / ".openclaw/workspace/skills"
sys.path.insert(0, str(SKILLS_DIR))


def load_skills_md(agent: str) -> str:
    """读取Agent的SKILLS.md文件"""
    skills_path = Path.home() / f".openclaw/workspace/ai-team/{agent}/SKILLS.md"
    
    if not skills_path.exists():
        # 尝试从skills目录读取
        skills_path = Path.home() / f".openclaw/workspace/skills/{agent}/SKILL.md"
    
    if skills_path.exists():
        with open(skills_path, "r") as f:
            return f.read()
    
    return ""


def detect_skill_from_task(task_desc: str, skills_md: str) -> str:
    """
    从任务描述和SKILLS.md中检测应该使用哪个技能
    这是一个简化版，实际应由Agent自己判断
    """
    task_lower = task_desc.lower()
    
    # 关键词映射
    skill_keywords = {
        "wechat-prompt-context": ["公众号", "微信文章", "公众号文章"],
        "xiaohongshu-content": ["小红书", "小红书文案", "小红书图文"],
        "juejin-publisher": ["掘金", "掘金文章"],
        "zhihu-post": ["知乎", "知乎回答", "知乎文章"],
        "baidu-search": ["搜索", "百度搜索"],
        "tavily-search-openclaw": ["搜索", "tavily"],
        "github-projects": ["github", "project"],
        "feishu-create-doc": ["飞书文档", "创建文档"],
        "feishu-bitable": ["多维表格", "飞书表格"],
    }
    
    for skill, keywords in skill_keywords.items():
        for kw in keywords:
            if kw in task_lower:
                return skill
    
    return ""


def execute_skill(skill_name: str, task_desc: str) -> bool:
    """
    执行技能
    这里只是一个占位符，实际执行由Agent自己完成
    """
    print(f"\n🔧 建议使用的技能: {skill_name}")
    print(f"📝 任务描述: {task_desc}")
    print(f"\n⚠️  请手动执行对应的技能")
    
    return True


def mark_github_complete(item_id: str) -> bool:
    """调用task_scheduler标记任务完成"""
    scheduler_path = Path.home() / ".openclaw/workspace/skills/github-projects/task_scheduler.py"
    
    try:
        result = subprocess.run(
            ["python3", str(scheduler_path), "--complete", item_id],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            print(f"✅ GitHub任务已标记完成")
            return True
        else:
            print(f"❌ 标记完成失败: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ 调用失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="GitHub Projects Agent 任务执行器")
    parser.add_argument("--file", type=str, help="任务文件路径")
    parser.add_argument("--agent", type=str, help="Agent ID")
    parser.add_argument("--task", type=str, help="任务描述")
    parser.add_argument("--item-id", type=str, help="GitHub任务ID")
    parser.add_argument("--complete", action="store_true", help="仅标记完成")
    args = parser.parse_args()
    
    # 从文件读取任务
    if args.file:
        with open(args.file, "r") as f:
            task_data = json.load(f)
        
        agent = task_data.get("agent", "main")
        task_desc = task_data.get("title", "")
        body = task_data.get("body", "")
        item_id = task_data.get("item_id", "")
    else:
        agent = args.agent or "main"
        task_desc = args.task or ""
        body = ""
        item_id = args.item_id or ""
    
    if not item_id:
        print("❌ 请提供 --item-id 或 --file")
        return 1
    
    # 仅标记完成
    if args.complete:
        return 0 if mark_github_complete(item_id) else 1
    
    print(f"\n{'='*60}")
    print(f"🤖 Agent: {agent}")
    print(f"📋 任务: {task_desc}")
    print(f"🆔 任务ID: {item_id}")
    print(f"{'='*60}")
    
    # 读取SKILLS.md
    print(f"\n📖 读取 {agent}/SKILLS.md...")
    skills_md = load_skills_md(agent)
    
    if skills_md:
        print(f"✅ 已加载技能文档")
    else:
        print(f"⚠️  未找到技能文档，使用默认处理")
    
    # 检测技能
    full_task = f"{task_desc} {body}".strip()
    suggested_skill = detect_skill_from_task(full_task, skills_md)
    
    if suggested_skill:
        print(f"\n💡 建议技能: {suggested_skill}")
    
    # 执行任务
    print(f"\n{'='*60}")
    print(f"🚀 开始执行任务...")
    print(f"{'='*60}")
    
    # 这里只是引导，实际执行由Agent自己完成
    print(f"\n请根据SKILLS.md的指引，调用相应的技能完成任务。")
    print(f"完成后运行以下命令标记完成：")
    print(f"   python3 ~/.openclaw/workspace/skills/github-projects/agent_runner.py --complete --item-id {item_id}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
