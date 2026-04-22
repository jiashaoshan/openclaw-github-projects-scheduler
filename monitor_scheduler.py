#!/usr/bin/env python3
"""
GitHub Projects 调度器监控脚本
监控 /tmp/gh_scheduler.log，发现异常时发送告警
"""

import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

LOG_FILE = "/tmp/gh_scheduler.log"
ALERT_COOLDOWN_FILE = "/tmp/gh_scheduler_alert_cooldown"
COOLDOWN_MINUTES = 30  # 告警冷却时间（避免重复告警）

def check_cooldown() -> bool:
    """检查是否在冷却期内"""
    if not os.path.exists(ALERT_COOLDOWN_FILE):
        return True
    
    with open(ALERT_COOLDOWN_FILE, "r") as f:
        last_alert = f.read().strip()
    
    if last_alert:
        try:
            last_time = datetime.fromisoformat(last_alert)
            if datetime.now() - last_time < timedelta(minutes=COOLDOWN_MINUTES):
                return False  # 在冷却期内
        except:
            pass
    
    return True

def set_cooldown():
    """设置告警冷却时间"""
    with open(ALERT_COOLDOWN_FILE, "w") as f:
        f.write(datetime.now().isoformat())

def analyze_log() -> dict:
    """分析日志文件，返回状态"""
    if not os.path.exists(LOG_FILE):
        return {
            "status": "warning",
            "message": "日志文件不存在，调度器可能未运行",
            "errors": []
        }
    
    # 读取最近100行
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-100:]
    except Exception as e:
        return {
            "status": "error",
            "message": f"读取日志失败: {e}",
            "errors": []
        }
    
    # 检查错误模式
    error_patterns = [
        (r"CLI调用失败|Command failed", "CLI调用失败"),
        (r"Agent启动失败|❌ Agent启动失败", "Agent启动失败"),
        (r"Error|Exception|Traceback", "调度器异常"),
        (r"HTTP Error|GraphQL Error", "GitHub API错误"),
    ]
    
    errors = []
    for line in lines:
        for pattern, error_type in error_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                # 提取时间戳和错误信息
                timestamp_match = re.match(r"\[(\d{2}:\d{2}:\d{2})\]", line)
                timestamp = timestamp_match.group(1) if timestamp_match else "未知时间"
                errors.append({
                    "time": timestamp,
                    "type": error_type,
                    "line": line.strip()
                })
    
    # 检查最近运行状态
    recent_lines = lines[-20:] if len(lines) >= 20 else lines
    recent_text = "".join(recent_lines)
    
    if "✅ 本次触发" in recent_text:
        # 调度器正常运行
        if errors:
            return {
                "status": "warning",
                "message": f"调度器运行正常，但发现 {len(errors)} 个错误",
                "errors": errors[-5:]  # 只返回最近5个
            }
        else:
            return {
                "status": "ok",
                "message": "调度器运行正常，无错误",
                "errors": []
            }
    elif "获取到" in recent_text and "个任务" in recent_text:
        # 有任务但未触发（可能是时间未到）
        return {
            "status": "ok",
            "message": "调度器运行中，等待任务触发",
            "errors": errors[-3:] if errors else []
        }
    else:
        # 可能未正常运行
        return {
            "status": "error",
            "message": "调度器可能未正常运行，请检查",
            "errors": errors[-5:] if errors else []
        }

def send_alert(status: dict):
    """发送告警（通过 OpenClaw CLI）"""
    import subprocess
    
    # 构建告警消息
    emoji_map = {
        "ok": "✅",
        "warning": "⚠️",
        "error": "🚨"
    }
    
    emoji = emoji_map.get(status["status"], "❓")
    
    message = f"""
{emoji} 【运维】GitHub Projects 调度器监控告警

状态: {status['status'].upper()}
时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
消息: {status['message']}
"""
    
    if status['errors']:
        message += "\n最近错误:\n"
        for err in status['errors'][:3]:
            message += f"  - [{err['time']}] {err['type']}\n"
    
    message += f"\n日志文件: {LOG_FILE}"
    
    # 通过 OpenClaw 发送消息到群
    home = Path.home()
    openclaw_path = str(home / ".npm-global" / "bin" / "openclaw")
    
    try:
        # 设置完整 PATH，确保 crontab 环境下能找到 node
        env = os.environ.copy()
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
        env["NO_COLOR"] = "1"
        
        # 使用 message 命令发送到飞书群
        cmd = [
            openclaw_path, "message", "send",
            "--channel", "feishu",
            "--target", "oc_1d05adec7a7ee7b58bf89b9ecc718378",
            "--text", message
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )
        
        if result.returncode == 0:
            print(f"✅ 告警已发送: {status['status']}")
            return True
        else:
            print(f"❌ 发送失败: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ 发送异常: {e}")
        return False

def main():
    """主函数"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始监控调度器...")
    
    status = analyze_log()
    
    print(f"状态: {status['status']}")
    print(f"消息: {status['message']}")
    
    # 只在异常时发送告警
    if status['status'] in ['warning', 'error']:
        if check_cooldown():
            if send_alert(status):
                set_cooldown()
        else:
            print("⏸️  在冷却期内，跳过告警")
    else:
        print("✅ 运行正常，无需告警")
    
    # 输出到日志
    with open("/tmp/gh_monitor.log", "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {status['status']}: {status['message']}\n")

if __name__ == "__main__":
    main()
