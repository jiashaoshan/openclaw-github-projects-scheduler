# HEARTBEAT.md - GitHub Projects 任务调度

## GitHub Projects 任务调度（每分钟检查）

调用独立脚本检查任务：

```bash
python3 ~/.openclaw/workspace/skills/github-projects/main_agent_heartbeat.py
```

脚本功能：
- 检查 `/tmp/gh_tasks/` 目录下的任务文件
- 发现 pending 任务时，标记为 processing
- 通过 `sessions_spawn` 启动对应 Agent 执行任务
- 记录执行日志到 `/tmp/main_agent_heartbeat.log`
