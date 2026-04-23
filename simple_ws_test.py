#!/usr/bin/env python3
"""
简单的WebSocket连接测试
"""

import asyncio
import json
import sys

try:
    import websockets
except ImportError:
    print("❌ 缺少 websockets，请先安装: pip install websockets")
    sys.exit(1)

async def test_simple():
    print("测试WebSocket连接...")
    
    try:
        # 连接
        ws = await websockets.connect("ws://127.0.0.1:18789")
        print("✅ WebSocket连接成功")
        
        # 接收第一个消息（应该是connect.challenge）
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            print(f"收到消息: {msg.get('event', 'unknown')}")
            
            if msg.get("event") == "connect.challenge":
                print("✅ 收到 connect.challenge")
                nonce = msg.get("payload", {}).get("nonce", "")
                print(f"Nonce: {nonce[:20]}...")
            else:
                print(f"⚠️ 预期 connect.challenge，收到: {msg}")
                
        except asyncio.TimeoutError:
            print("❌ 超时：未收到 connect.challenge")
        
        await ws.close()
        print("✅ 连接关闭")
        return True
        
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_simple())
    sys.exit(0 if success else 1)
