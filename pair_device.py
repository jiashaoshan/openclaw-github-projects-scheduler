#!/usr/bin/env python3
"""
设备配对脚本 - 通过 WebSocket 发送 pair.approve 请求
"""

import asyncio
import json
import uuid
import websockets
import time
import base64
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

async def pair_device():
    """发送设备配对请求"""
    device_id = "3c45559fa664890d6c970fcdb6c279bd67a2c5e785ed643b003685925bfbc530"
    
    async with websockets.connect('ws://127.0.0.1:18789') as ws:
        # 1. 接收 challenge
        chal = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        logger.info(f"Challenge: {chal}")
        
        if chal.get("event") != "connect.challenge":
            logger.error(f"Expected challenge, got: {chal}")
            return
        
        nonce = chal["payload"]["nonce"]
        
        # 2. 使用已有的 admin token 发送 pair.approve
        req = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "pair.approve",
            "params": {
                "deviceId": device_id,
                "role": "operator",
                "scopes": ["operator.read", "operator.write", "operator.admin"]
            }
        }
        
        # 需要认证才能发送 pair.approve
        # 尝试使用 token 认证
        auth_req = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {
                    "id": "cli",
                    "version": "1.0.0",
                    "platform": "macos",
                    "mode": "cli",
                    "deviceFamily": "admin-cli"
                },
                "role": "operator",
                "scopes": ["operator.admin", "operator.pairing"],
                "auth": {"token": "aa77e05531fa4da9c57bc54f30c92011eef5b6135df11985"}
            }
        }
        
        await ws.send(json.dumps(auth_req))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        logger.info(f"Auth response: {json.dumps(resp, indent=2)}")
        
        if resp.get("ok"):
            # 认证成功，发送 pair.approve
            await ws.send(json.dumps(req))
            pair_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            logger.info(f"Pair response: {json.dumps(pair_resp, indent=2)}")

if __name__ == "__main__":
    asyncio.run(pair_device())
