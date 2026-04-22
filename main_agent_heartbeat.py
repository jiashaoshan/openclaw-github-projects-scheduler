#!/usr/bin/env python3
"""
主 Agent HEARTBEAT 脚本 - GitHub Projects 任务调度

功能：
1. 每分钟检查 /tmp/gh_tasks/ 目录下的任务文件
2. 发现 pending 任务时，标记为 processing
3. 通过 sessions_spawn 启动对应 Agent 执行任务
4. 记录执行日志到 /tmp/main_agent_heartbeat.log

使用方法：
    python3 main_agent_heartbeat.py

配置：
    该脚本由 OpenClaw HEARTBEAT 每分钟调用
"""

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

def log_message(msg: str):
    """记录日志到文件"""
    log_file = "/tmp/main_agent_heartbeat.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {msg}"
    
    try:
        with open(log_file, "a") as f:
            f.write(log_entry + "\n")
    except Exception as e:
        print(f"日志写入失败: {e}")
    
    print(log_entry)

def spawn_agent(agent_name: str, task: dict):
    """使用 openclaw CLI 启动子 Agent 执行任务"""
    try:
        # 构建任务消息
        task_message = f"""执行 GitHub Projects 任务

任务标题: {task['title']}
任务描述: {task['body']}
任务ID: {task['item_id']}

请按以下步骤执行：
1. 读取 ~/.openclaw/workspace/ai-team/{agent_name}/SKILLS.md
2. 根据任务描述找到匹配的技能路由
3. 调用对应技能完成任务
4. 执行完成后更新 GitHub 状态：
   python3 ~/.openclaw/workspace/skills/github-projects/task_scheduler_v2.py --complete {task['item_id']} --agent {agent_name}
5. 在群里汇报结果（使用自己的飞书Bot账号）
"""
        
        # 使用 openclaw agent 命令启动子 Agent
        # 注意：这里使用 --to 指定目标，实际使用时可能需要调整
        cmd = [
            "openclaw", "agent",
            "--message", task_message,
            "--timeout", "300"  # 5分钟超时
        ]
        
        log_message(f"启动 Agent [{agent_name}] 执行任务: {task['title'][:30]}...")
        
        # 异步启动子进程
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True  # 独立进程组
        )
        
        return True
        
    except Exception as e:
        log_message(f"启动 Agent 失败: {e}")
        return False

def check_github_project_tasks():
    """检查 GitHub Projects 任务文件并分发"""
    tasks_dir = Path("/tmp/gh_tasks")
    triggered = []
    
    if not tasks_dir.exists():
        return None, "无任务目录"
    
    # 遍历所有 Agent 的任务目录
    for agent_dir in tasks_dir.iterdir():
        if not agent_dir.is_dir() or agent_dir.name == "archive":
            continue
        
        agent_name = agent_dir.name
        
        # 查找 pending 状态的任务
        for task_file in agent_dir.glob("*.json"):
            try:
                with open(task_file) as f:
                    task = json.load(f)
                
                if task.get("status") != "pending":
                    continue
                
                # 标记为 processing
                task["status"] = "processing"
                task["started_at"] = datetime.now().isoformat()
                with open(task_file, 'w') as f:
                    json.dump(task, f)
                
                # 启动对应 Agent 执行任务
                if spawn_agent(agent_name, task):
                    triggered.append({
                        "agent": agent_name,
                        "title": task['title'],
                        "item_id": task['item_id']
                    })
                    log_message(f"已分发任务: [{agent_name}] {task['title'][:50]}...")
                
            except Exception as e:
                log_message(f"处理任务文件失败: {task_file}, {e}")
    
    return triggered

def main():
    """主入口"""
    log_message("开始检查 GitHub Projects 任务...")
    
    tasks = check_github_project_tasks()
    
    if tasks:
        result = f"【任务调度】已分发 {len(tasks)} 个任务"
        log_message(result)
        return result
    else:
        log_message("HEARTBEAT_OK")
        return "HEARTBEAT_OK"

if __name__ == "__main__":
    main()
