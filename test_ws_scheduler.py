#!/usr/bin/env python3
"""
测试WebSocket调度器的Agent调用功能（不依赖GitHub API）
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

try:
    import websockets
except ImportError:
    print("❌ 缺少 websockets，请先安装: pip install websockets")
    sys.exit(1)

# WebSocket配置
DEFAULT_WS_URL = "ws://127.0.0.1:18789"

class TestOpenClawClient:
    """测试OpenClaw WebSocket客户端"""
    
    def __init__(self, url: str = None):
        self.url = url or DEFAULT_WS_URL
        self.ws = None
        self.connect_nonce = None
    
    async def connect(self) -> bool:
        """连接 Gateway 并完成握手"""
        try:
            self.ws = await websockets.connect(self.url)
            # 等待 connect.challenge
            while True:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=10)
                evt = json.loads(raw)
                if evt.get("event") == "connect.challenge":
                    self.connect_nonce = evt.get("payload", {}).get("nonce")
                    break
            
            # 发送 connect 请求
            await self._send_connect()
            return True
        except Exception as e:
            print(f"❌ WebSocket连接失败: {e}")
            return False
    
    async def _send_connect(self):
        """发送 connect 握手请求"""
        import uuid
        req_id = str(uuid.uuid4())
        
        # 尝试从 openclaw.json 读取 token
        token = ""
        try:
            config_path = Path.home() / ".openclaw" / "openclaw.json"
            if config_path.exists():
                config = json.loads(config_path.read_text())
                token = config.get("gateway", {}).get("auth", {}).get("token", "")
        except Exception:
            pass
        
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
                    "token": token
                } if token else {},
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
    
    async def test_agent_call(self, agent_id: str = "main"):
        """测试调用Agent"""
        print(f"\n测试调用Agent [{agent_id}]...")
        
        task_message = f"""测试GitHub Projects调度器

这是一个测试任务，用于验证WebSocket调度器功能。

请回复：\"✅ WebSocket调度器测试成功，Agent [{agent_id}] 已就绪\"
"""
        
        import uuid
        req_id = f"test-{uuid.uuid4()}"
        create_frame = {
            "type": "req",
            "id": req_id,
            "method": "sessions.create",
            "params": {
                "agentId": agent_id,
                "message": task_message
            }
        }
        
        print(f"发送任务到Agent [{agent_id}]...")
        await self.ws.send(json.dumps(create_frame))
        
        chunks = []
        t0 = time.time()
        first_chunk = None
        
        while time.time() - t0 < 120:  # 2分钟超时
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=2)
                msg = json.loads(raw)
                
                # 检查 sessions.create 响应
                if msg.get("id") == req_id:
                    if msg.get("type") == "res":
                        if msg.get("ok"):
                            print("✅ 会话创建成功")
                        else:
                            print(f"❌ 会话创建失败: {msg}")
                            return False
                
                # 收集 agent 回复事件
                event_type = msg.get("event", "")
                payload = msg.get("payload", {})
                
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
                                    print(f"首字节延迟: {first_chunk:.2f}s")
                                chunks.append(text)
                                print(f"收到回复: {text[:100]}...")
                    
                    # final/complete 状态表示流结束
                    if state in ("final", "complete"):
                        print(f"✅ 任务执行完成，总耗时: {time.time() - t0:.1f}s")
                        break
                        
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"接收消息出错: {e}")
                break
        
        reply = "".join(chunks)
        print(f"\n完整回复: {reply}")
        return True
    
    async def close(self):
        if self.ws:
            await self.ws.close()


async def main():
    print("="*60)
    print("WebSocket调度器功能测试")
    print("="*60)
    
    # 1. 测试连接
    print("\n1. 测试WebSocket连接...")
    client = TestOpenClawClient()
    if not await client.connect():
        print("❌ 连接失败")
        return False
    print("✅ WebSocket连接成功")
    
    # 2. 测试调用main Agent
    success = await client.test_agent_call("main")
    
    # 3. 测试调用hermes Agent
    if success:
        success = await client.test_agent_call("hermes")
    
    await client.close()
    
    print("\n" + "="*60)
    if success:
        print("✅ 所有测试通过")
    else:
        print("❌ 测试失败")
    print("="*60)
    
    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
