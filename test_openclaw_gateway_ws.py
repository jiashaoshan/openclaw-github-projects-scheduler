#!/usr/bin/env python3
"""
OpenClaw Gateway WebSocket 连接测试脚本

OpenClaw Gateway 使用自定义 WebSocket JSON-RPC 协议（非标准 WebSocket）:
  1. 连接 ws://host:port
  2. 服务端推送 connect.challenge（含 nonce）
  3. 客户端发送 connect 请求（含 auth token）
  4. 服务端返回 hello.ok
  5. 客户端发送 chat.send / sessions.list 等请求

用法:
  python test_openclaw_gateway_ws.py                    # 默认 ws://127.0.0.1:18789
  python test_openclaw_gateway_ws.py --url ws://xxx     # 指定 URL
  python test_openclaw_gateway_ws.py --token xxx        # 指定 token
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
import uuid

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
except ImportError:
    print("❌ 缺少 websockets，请先安装: pip install websockets")
    sys.exit(1)

# ─── 配置 ──────────────────────────────────────────────
DEFAULT_WS_URL = "ws://127.0.0.1:18789"
DEFAULT_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")

# ─── 颜色 ──────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def status(icon, label, passed=True):
    color = GREEN if passed else RED
    mark = "✅" if passed else "❌"
    print(f"  {color}{mark} {label}{RESET}")


class OpenClawGatewayClient:
    """OpenClaw Gateway WebSocket 客户端"""

    def __init__(self, url, token=None):
        self.url = url
        self.token = token or DEFAULT_GATEWAY_TOKEN
        self.ws = None
        self.connect_nonce = None
        self.request_id = 0
        self.pending_requests = {}
        self.received_events = []

    async def connect(self):
        """连接 Gateway 并完成握手"""
        self.ws = await websockets.connect(self.url)
        # 等待 connect.challenge
        while True:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=10)
            evt = json.loads(raw)
            if evt.get("event") == "connect.challenge":
                self.connect_nonce = evt.get("payload", {}).get("nonce")
                break
            self.received_events.append(evt)

        # 发送 connect 请求
        await self._send_connect()
        return True

    async def _send_connect(self):
        """发送 connect 握手请求"""
        req_id = str(uuid.uuid4())
        frame = {
            "type": "req",
            "id": req_id,
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {
                    "id": "gateway-client",
                    "version": "1.0.0-test",
                    "platform": sys.platform,
                    "mode": "backend"
                },
                "auth": {
                    "token": self.token
                } if self.token else {},
                "role": "operator",
                "scopes": ["operator.admin"],
                "caps": []
            }
        }
        await self.ws.send(json.dumps(frame))

        # 等待 hello.ok
        while True:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=10)
            msg = json.loads(raw)
            if msg.get("id") == req_id:
                if msg.get("type") == "res":
                    return msg
                elif msg.get("type") == "err":
                    raise Exception(f"connect failed: {msg}")
            self.received_events.append(msg)

    async def request(self, method, params=None, timeout=60):
        """发送 RPC 请求并等待响应"""
        self.request_id += 1
        req_id = f"req-{self.request_id}"
        frame = {
            "type": "req",
            "id": req_id,
            "method": method,
            "params": params or {}
        }
        await self.ws.send(json.dumps(frame))

        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=2)
                msg = json.loads(raw)
                if msg.get("id") == req_id:
                    # OpenClaw 返回 payload 而不是 result，统一包装
                    if msg.get("type") == "res" and msg.get("ok"):
                        return {"type": "res", "ok": True, "result": msg.get("payload", {})}
                    return msg
                self.received_events.append(msg)
            except asyncio.TimeoutError:
                continue
        return {"type": "timeout", "method": method}

    async def create_session_and_chat(self, message, agent_id="hermes", timeout=120):
        """创建会话并发送消息，返回回复"""
        # 1. 创建会话
        self.request_id += 1
        create_req_id = f"session-create-{self.request_id}"
        create_frame = {
            "type": "req",
            "id": create_req_id,
            "method": "sessions.create",
            "params": {
                "agentId": agent_id,
                "message": message
            }
        }
        await self.ws.send(json.dumps(create_frame))

        chunks = []
        session_key = None
        run_id = None
        t0 = time.time()
        first_chunk = None

        while time.time() - t0 < timeout:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=2)
                msg = json.loads(raw)

                # 检查 sessions.create 响应
                if msg.get("id") == create_req_id:
                    if msg.get("type") == "res":
                        if msg.get("ok"):
                            payload = msg.get("payload", {})
                            session_key = payload.get("key")
                            run_id = payload.get("runId")
                        else:
                            return {"error": msg.get("error", {}), "chunks": []}
                        # 继续收集 delta 事件直到流结束

                # 收集 agent 回复事件
                event_type = msg.get("event", "")
                payload = msg.get("payload", {})

                # chat 事件包含回复内容
                if event_type == "chat" and isinstance(payload, dict):
                    state = payload.get("state", "")
                    message = payload.get("message", {})
                    if isinstance(message, dict):
                        content_list = message.get("content", [])
                        if isinstance(content_list, list) and len(content_list) > 0:
                            text = content_list[0].get("text", "")
                            if text:
                                if first_chunk is None:
                                    first_chunk = time.time() - t0
                                chunks.append(text)
                    # final/complete 状态表示流结束
                    if state in ("final", "complete"):
                        break

                self.received_events.append(msg)
            except asyncio.TimeoutError:
                continue

        return {
            "session_key": session_key,
            "run_id": run_id,
            "chunks": chunks,
            "ttft": first_chunk,
            "elapsed": time.time() - t0
        }

    async def send_chat(self, message, timeout=120):
        """发送聊天消息并等待回复（使用 sessions.create）"""
        return await self.create_session_and_chat(message, timeout=timeout)
        await self.ws.send(json.dumps(frame))

        chunks = []
        final_result = None
        t0 = time.time()
        first_chunk = None
        while time.time() - t0 < timeout:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=2)
                msg = json.loads(raw)

                # 检查是否是我们的请求的响应
                if msg.get("id") == req_id:
                    if msg.get("type") == "res":
                        final_result = msg
                        break
                    elif msg.get("type") == "err":
                        return {"error": msg}

                # 收集 agent 输出事件
                event_type = msg.get("event", "")
                msg_type = msg.get("type", "")
                payload = msg.get("payload", {})

                if event_type == "delta" or msg_type == "delta":
                    if first_chunk is None:
                        first_chunk = time.time() - t0
                    # payload 可能是直接的 content 字符串或 dict
                    if isinstance(payload, str):
                        chunks.append(payload)
                    else:
                        content = payload.get("content", "")
                        if content:
                            chunks.append(content)
                        # 也检查 text 字段
                        text = payload.get("text", "")
                        if text and not content:
                            chunks.append(text)

                self.received_events.append(msg)
            except asyncio.TimeoutError:
                continue

        return {
            "chunks": chunks,
            "final": final_result,
            "ttft": first_chunk,
            "elapsed": time.time() - t0
        }

    async def close(self):
        if self.ws:
            await self.ws.close()


async def test_connect(ws_url, token):
    """测试 1: 连接 + 握手"""
    print(f"\n{BOLD}{CYAN}[Test 1] WebSocket 连接 + 握手 — {ws_url}{RESET}")
    try:
        client = OpenClawGatewayClient(ws_url, token)
        result = await client.connect()
        status("WebSocket 连接", "连接成功")
        status("connect.challenge", f"收到 nonce: {client.connect_nonce[:8]}..." if client.connect_nonce else "未收到")
        status("hello.ok", "握手成功")
        await client.close()
        return True
    except Exception as e:
        status("连接", f"失败: {e}", passed=False)
        return False


async def test_sessions_list(ws_url, token):
    """测试 2: 获取会话列表"""
    print(f"\n{BOLD}{CYAN}[Test 2] sessions.list — 获取会话列表{RESET}")
    try:
        client = OpenClawGatewayClient(ws_url, token)
        await client.connect()
        result = await client.request("sessions.list", {"limit": 5})
        if result.get("type") == "res":
            sessions = result.get("result", {}).get("sessions", [])
            status("sessions.list", f"找到 {len(sessions)} 个会话")
        else:
            status("sessions.list", f"响应: {json.dumps(result)[:100]}")
        await client.close()
        return True
    except Exception as e:
        status("sessions.list", f"失败: {e}", passed=False)
        return False


async def test_chat_send(ws_url, token):
    """测试 3: 发送聊天消息"""
    print(f"\n{BOLD}{CYAN}[Test 3] sessions.create + chat — 发送消息{RESET}")
    try:
        client = OpenClawGatewayClient(ws_url, token)
        await client.connect()
        result = await client.create_session_and_chat("你好，请用一句话介绍你自己")
        if result.get("error"):
            status("sessions.create", f"错误: {result['error']}", passed=False)
            return False
        reply = "".join(result["chunks"])
        session_key = result.get("session_key", "unknown")
        if session_key and len(session_key) > 40:
            status("sessions.create", f"会话: {session_key[:40]}...")
        else:
            status("sessions.create", f"会话: {session_key}")
        status("回复", f"{reply[:120]}..." if reply else "(空)")
        status("首字节延迟", f"{result['ttft']:.2f}s" if result['ttft'] else "N/A")
        status("总耗时", f"{result['elapsed']:.1f}s")
        await client.close()
        return True
    except Exception as e:
        status("chat.send", f"失败: {e}", passed=False)
        return False


async def test_chat_stream(ws_url, token):
    """测试 4: 流式对话（观察 delta 事件）"""
    print(f"\n{BOLD}{CYAN}[Test 4] sessions.create (流式) — 观察 delta 事件{RESET}")
    try:
        client = OpenClawGatewayClient(ws_url, token)
        await client.connect()
        result = await client.create_session_and_chat("列出5种编程语言的名字，每行一个", timeout=120)
        if result.get("error"):
            status("流式", f"错误: {result['error']}", passed=False)
            return False
        reply = "".join(result["chunks"])
        chunk_count = len(result["chunks"])
        status("流式", f"收到 {chunk_count} 个 chunk")
        status("完整回复", f"{reply[:120]}...")
        await client.close()
        return True
    except Exception as e:
        status("流式", f"失败: {e}", passed=False)
        return False


async def test_agent_status(ws_url, token):
    """测试 5: 获取 agent 状态"""
    print(f"\n{BOLD}{CYAN}[Test 5] agent.status — Agent 状态{RESET}")
    try:
        client = OpenClawGatewayClient(ws_url, token)
        await client.connect()
        result = await client.request("agent.status")
        if result.get("type") == "res":
            data = result.get("result", {})
            status("agent.status", f"状态: {json.dumps(data)[:120]}")
        else:
            status("agent.status", f"响应: {json.dumps(result)[:100]}")
        await client.close()
        return True
    except Exception as e:
        status("agent.status", f"失败: {e}", passed=False)
        return False


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="OpenClaw Gateway WebSocket 测试")
    parser.add_argument("--url", default=None, help="WebSocket URL (默认: ws://127.0.0.1:18789)")
    parser.add_argument("--token", default=None, help="Gateway token")
    parser.add_argument("--test", default="all",
                        help="单个测试: connect, sessions, chat, stream, status, 或 all")
    args = parser.parse_args()

    ws_url = args.url or DEFAULT_WS_URL
    token = args.token or DEFAULT_GATEWAY_TOKEN

    if not token:
        # 尝试从 openclaw.json 读取 token
        try:
            config_path = Path.home() / ".openclaw" / "openclaw.json"
            if config_path.exists():
                config = json.loads(config_path.read_text())
                token = config.get("gateway", {}).get("auth", {}).get("token", "")
        except Exception:
            pass

    print(f"{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  OpenClaw Gateway — WebSocket 连接测试{RESET}")
    print(f"{BOLD}  地址: {ws_url}{RESET}")
    print(f"{BOLD}  Token: {'***' + token[-6:] if len(token) > 6 else '(空)'}{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    tests = {
        "connect": lambda: test_connect(ws_url, token),
        "sessions": lambda: test_sessions_list(ws_url, token),
        "chat": lambda: test_chat_send(ws_url, token),
        "stream": lambda: test_chat_stream(ws_url, token),
        "status": lambda: test_agent_status(ws_url, token),
    }

    if args.test == "all":
        selected = tests
    elif args.test in tests:
        selected = {args.test: tests[args.test]}
    else:
        print(f"{RED}未知测试: {args.test}{RESET}")
        print(f"可用: {', '.join(tests.keys())}")
        return

    results = {}
    for name, fn in selected.items():
        results[name] = await fn()

    # ─── 汇总 ─────────────────────────────────────────
    print(f"\n{BOLD}{'='*60}{RESET}")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    color = GREEN if passed == total else YELLOW
    print(f"{BOLD}{color}  结果: {passed}/{total} 通过{RESET}")
    for name, ok in results.items():
        mark = "✅" if ok else "❌"
        print(f"    {mark} {name}")
    print(f"{BOLD}{'='*60}{RESET}")

    if passed < total:
        print(f"\n{YELLOW}提示:{RESET}")
        print(f"  1. 确认 Gateway 正在运行: openclaw gateway status")
        print(f"  2. 确认 Token 正确: openclaw gateway token")
        print(f"  3. 检查端口: ss -tlnp | grep 18789")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{YELLOW}已中断{RESET}")
