# HEARTBEAT.md - GitHub Projects 任务调度

## GitHub Projects 任务调度（每分钟检查）

```python
import json
from pathlib import Path
from sessions_spawn import sessions_spawn
from datetime import datetime

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
                sessions_spawn({
                    "task": f"""执行 GitHub Projects 任务

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
""",
                    "runtime": "subagent",
                    "label": f"{agent_name}-github-task",
                    "mode": "run"
                })
                
                triggered.append({
                    "agent": agent_name,
                    "title": task['title'],
                    "item_id": task['item_id']
                })
                
            except Exception as e:
                print(f"处理任务文件失败: {task_file}, {e}")
    
    return triggered

# HEARTBEAT 入口
tasks = check_github_project_tasks()
if tasks:
    return f"【任务调度】已分发 {len(tasks)} 个任务:\n" + "\n".join([f"- [{t['agent']}] {t['title'][:30]}..." for t in tasks])
else:
    return "HEARTBEAT_OK"
```


