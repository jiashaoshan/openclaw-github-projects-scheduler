#!/usr/bin/env python3
"""
OpenClaw CLI 生产级客户端封装 - 修正版
修复：agent 命令语法错误，移除多余的 "run" 子命令
"""

import subprocess
import json
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, asdict
from enum import Enum
import threading
import uuid

# ============ 配置 ============
LOG_LEVEL = logging.INFO
LOG_FILE = Path.home() / "Library" / "Logs" / "openclaw_cli_client.log"
DEFAULT_TIMEOUT = 300
POLL_INTERVAL = 2
MAX_RETRIES = 3

# ============ 日志配置 ============
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8", mode="a"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============ 数据类型 ============
class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class TaskResult:
    run_id: str
    status: TaskStatus
    output: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


# ============ 核心客户端 ============
class OpenClawCLIClient:
    def __init__(self, token: str, base_cmd: list = None):
        self.token = token
        # 使用完整路径，避免 crontab 环境下 PATH 问题
        # openclaw 安装在 ~/.npm-global/bin/
        home = Path.home()
        openclaw_path = str(home / ".npm-global" / "bin" / "openclaw")
        self.base_cmd = base_cmd or [openclaw_path]

    def _env(self) -> Dict[str, str]:
        import os
        env = os.environ.copy()
        env["OPENCLAW_TOKEN"] = self.token
        env["NO_COLOR"] = "1"  # 禁用颜色输出
        
        # 设置完整 PATH，确保 crontab 环境下能找到 node 和其他命令
        home = str(Path.home())
        paths = [
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
            f"{home}/.npm-global/bin",
            f"{home}/.local/bin",
            "/opt/homebrew/bin",
        ]
        env["PATH"] = ":".join(paths) + ":" + env.get("PATH", "")
        
        return env

    def _run_cmd(self, cmd: list, timeout: int = 30, retries: int = MAX_RETRIES) -> subprocess.CompletedProcess:
        """执行命令 + 自动重试"""
        last_error = None
        for attempt in range(retries):
            try:
                logger.debug(f"Running: {' '.join(cmd)} (attempt {attempt+1})")
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout,
                    env=self._env(), check=False
                )
                if result.returncode == 0:
                    return result
                last_error = result.stderr.strip()
                if attempt < retries - 1:
                    time.sleep(1 * (attempt + 1))
            except subprocess.TimeoutExpired:
                last_error = f"Timeout after {timeout}s"
            except Exception as e:
                last_error = str(e)
        raise RuntimeError(f"Command failed after {retries} attempts: {last_error}")

    def send_message(
        self,
        message: str,
        agent_id: str = "main",
        session_id: str = None,
        to_dest: str = None,
        wait: bool = True,
        timeout: int = DEFAULT_TIMEOUT,
        json_output: bool = True
    ) -> TaskResult:
        """
        发送消息给 Agent（修正版：使用正确 CLI 语法）

        Args:
            message: 消息内容（必需）
            agent_id: 目标 agent ID（--agent 参数）
            session_id: 显式会话 ID（--session-id 参数，优先级高于 agent_id）
            to_dest: 收件人地址（--to 参数，如电话/邮箱）
            wait: 是否阻塞等待（通过 --timeout 控制）
            timeout: 执行超时（秒）
            json_output: 是否请求 JSON 输出

        Returns:
            TaskResult: 结构化结果
        """
        # ✅ 关键修复：移除 "run"，直接使用 openclaw agent [OPTIONS]
        cmd = self.base_cmd + ["agent"]

        # 添加会话选择器（三选一，必需）
        if session_id:
            cmd += ["--session-id", session_id]
        elif to_dest:
            cmd += ["--to", to_dest]
        else:
            cmd += ["--agent", agent_id]  # 默认使用 agent_id

        # 添加必需的消息参数
        cmd += ["--message", message]

        # 添加可选参数
        if wait:
            cmd += ["--timeout", str(timeout)]
        if json_output:
            cmd += ["--json"]

        start_time = time.time()
        run_id = f"{agent_id}-{uuid.uuid4().hex[:8]}"
        result = TaskResult(run_id=run_id, status=TaskStatus.PENDING, started_at=start_time)

        try:
            # 执行命令
            proc = self._run_cmd(cmd, timeout=timeout + 10)

            # 解析输出
            output = proc.stdout.strip()
            if output and json_output:
                try:
                    data = json.loads(output)
                    result.output = data.get("output") or data.get("result") or str(data)
                    result.metadata = {k: v for k, v in data.items() if k not in ["output", "result"]}
                    result.status = TaskStatus.COMPLETED if proc.returncode == 0 else TaskStatus.FAILED
                    if not result.output and proc.returncode != 0:
                        result.error = data.get("error") or proc.stderr.strip()
                except json.JSONDecodeError:
                    result.output = output
                    result.status = TaskStatus.COMPLETED if proc.returncode == 0 else TaskStatus.FAILED
            else:
                result.output = output
                result.status = TaskStatus.COMPLETED if proc.returncode == 0 else TaskStatus.FAILED
                if proc.returncode != 0:
                    result.error = proc.stderr.strip()

            result.completed_at = time.time()
            logger.info(f"Task {run_id} finished: {result.status.value}")
            return result

        except RuntimeError as e:
            result.status = TaskStatus.FAILED
            result.error = str(e)
            logger.error(f"Task {run_id} failed: {e}")
            return result

    def spawn_subagent_via_message(
        self,
        task: str,
        agent_id: str = "main",
        label: str = None,
        wait: bool = False,  # 默认不等待，避免超时
        timeout: int = 60,
        **kwargs
    ) -> TaskResult:
        """
        通过发送消息间接触发子 Agent（/subagents spawn 命令）
        
        注意：默认 wait=False，因为子 Agent 执行可能耗时较长。
        如果需要等待结果，请设置 wait=True 和合适的 timeout。

        Args:
            task: 子 Agent 的任务描述
            agent_id: 主 Agent ID
            label: 任务标签（用于日志筛选）
            wait: 是否等待完成（默认 False，异步启动）
            timeout: 等待超时（仅当 wait=True 时有效）
            **kwargs: 透传给 send_message 的参数
        """
        label = label or f"task-{int(time.time())}"
        # 构造 spawn 指令（作为消息内容发送）
        # 使用 --detach 参数让子 Agent 在后台运行
        spawn_cmd = f"/subagents spawn --task \"{task}\" --mode run --label {label}"
        if not wait:
            # 不等待，直接返回启动结果
            return self.send_message(message=spawn_cmd, agent_id=agent_id, wait=False, timeout=10)
        else:
            # 等待完成
            return self.send_message(message=spawn_cmd, agent_id=agent_id, wait=True, timeout=timeout)


# ============ 便捷函数 ============
def spawn_agent(
    task: str,
    token: str,
    agent_id: str = "main",
    wait: bool = True,
    timeout: int = DEFAULT_TIMEOUT
) -> TaskResult:
    """便捷函数：触发子 Agent"""
    client = OpenClawCLIClient(token=token)
    return client.spawn_subagent_via_message(
        task=task,
        agent_id=agent_id,
        wait=wait,
        timeout=timeout,
        label=f"py-{uuid.uuid4().hex[:6]}"
    )


# ============ 使用示例 ============
if __name__ == "__main__":
    TOKEN = "aa77e05531fa4da9c57bc54f30c92011eef5b6135df11985"

    # 测试：触发子 Agent 执行任务
    print("🚀 测试 CLI 方式触发子 Agent...")
    client = OpenClawCLIClient(token=TOKEN)
    result = client.spawn_subagent_via_message(
        task="测试 CLI 方式启动子 Agent - 请回复 '测试成功'",
        agent_id="main",
        wait=True,
        timeout=60
    )
    print(f"✅ 状态: {result.status.value}")
    if result.output:
        print(f"📄 输出:\n{result.output}")
    if result.error:
        print(f"❌ 错误: {result.error}")
