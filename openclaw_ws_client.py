#!/usr/bin/env python3
"""
OpenClaw WebSocket 客户端 - 修正版
使用正确的默认值：clientId="gateway-client", clientMode="backend"
"""

import asyncio
import json
import uuid
import websockets
import time
import logging
import base64
import subprocess
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class OpenClawWSClient:
    # 正确的默认值（来自 OpenClaw 源码）
    CLIENT_ID = "gateway-client"
    CLIENT_MODE = "backend"
    ROLE = "operator"
    SCOPES = ["operator.admin"]

    def __init__(self, ws_url: str, auth_token: str = None):
        self.ws_url = ws_url
        self.auth_token = auth_token
        self.ws = None
        self.pending = {}
        self._load_device_identity()
        self._load_device_token()
    
    def _load_device_identity(self):
        """从 device.json 加载设备身份"""
        device_file = Path.home() / ".openclaw" / "identity" / "device.json"
        if not device_file.exists():
            raise FileNotFoundError(f"Device identity not found: {device_file}")
        
        with open(device_file) as f:
            data = json.load(f)
        
        self.device_id = data["deviceId"]
        self.public_key_pem = data["publicKeyPem"]
        self.private_key_pem = data["privateKeyPem"]
        
        logger.info(f"✅ 加载设备身份: {self.device_id[:16]}...")

    def _load_device_token(self):
        """从 device-auth.json 加载 device token"""
        auth_file = Path.home() / ".openclaw" / "identity" / "device-auth.json"
        if auth_file.exists():
            with open(auth_file) as f:
                data = json.load(f)
            if "tokens" in data and "operator" in data["tokens"]:
                self.device_token = data["tokens"]["operator"]["token"]
                logger.info(f"✅ 加载 device token: {self.device_token[:20]}...")
            else:
                self.device_token = ""
        else:
            self.device_token = ""

    def _sign_with_node(self, payload: str) -> str:
        """使用 Node.js 签名 payload"""
        sign_script = Path(__file__).parent / "sign_payload.js"
        result = subprocess.run(
            ["node", str(sign_script), payload],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            raise RuntimeError(f"Node.js 签名失败: {result.stderr}")
        return result.stdout.strip()

    def _build_payload_v3(self, device_id: str, client_id: str, client_mode: str,
                          role: str, scopes: list, signed_at_ms: int, token: str, nonce: str,
                          platform: str, device_family: str = None) -> str:
        """构建 V3 格式的 payload"""
        scopes_str = ",".join(scopes)
        platform_norm = platform.replace("darwin", "macos")
        
        parts = [
            "v3",
            device_id,
            client_id,
            client_mode,
            role,
            scopes_str,
            str(signed_at_ms),
            token if token else "",
            nonce,
            platform_norm
        ]
        
        if device_family:
            parts.append(device_family)
        
        return "|".join(parts)

    async def connect(self):
        """使用设备身份连接 WebSocket"""
        try:
            self.ws = await websockets.connect(self.ws_url, ping_interval=20, ping_timeout=10)
            
            # 1. 接收 challenge
            chal = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=5))
            if chal.get("event") != "connect.challenge":
                raise Exception(f"Expected challenge, got: {chal}")
            nonce = chal["payload"]["nonce"]
            
            # 2. 构建 payload (V3)
            signed_at_ms = int(time.time() * 1000)
            platform = "darwin"
            
            # signatureToken = authToken ?? null
            signature_token = self.auth_token or ""
            
            payload = self._build_payload_v3(
                device_id=self.device_id,
                client_id=self.CLIENT_ID,
                client_mode=self.CLIENT_MODE,
                role=self.ROLE,
                scopes=self.SCOPES,
                signed_at_ms=signed_at_ms,
                token=signature_token,
                nonce=nonce,
                platform=platform,
                device_family=""  # 添加空的 deviceFamily
            )
            
            logger.info(f"📋 Payload (V3): {payload}")
            
            # 3. 使用 Node.js 签名
            signature = self._sign_with_node(payload)
            logger.info(f"✅ 签名完成: {signature[:30]}...")
            
            # 4. 获取 raw public key (base64url)
            from cryptography.hazmat.primitives import serialization
            public_key = serialization.load_pem_public_key(self.public_key_pem.encode())
            public_key_bytes = public_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw
            )
            public_key_b64url = base64.b64encode(public_key_bytes).decode()
            public_key_b64url = public_key_b64url.replace("+", "-").replace("/", "_").rstrip("=")
            
            # 5. 构造 connect 请求
            req = {
                "type": "req",
                "id": str(uuid.uuid4()),
                "method": "connect",
                "params": {
                    "minProtocol": 3,
                    "maxProtocol": 3,
                    "client": {
                        "id": self.CLIENT_ID,
                        "version": "2026.4.15",
                        "platform": platform,
                        "mode": self.CLIENT_MODE
                    },
                    "auth": {"token": self.auth_token} if self.auth_token else {},
                    "device": {
                        "id": self.device_id,
                        "publicKey": public_key_b64url,
                        "signature": signature,
                        "signedAt": signed_at_ms,
                        "nonce": nonce
                    }
                }
            }
            
            await self.ws.send(json.dumps(req))
            resp = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=10))
            
            if resp.get("ok"):
                logger.info("✅ WebSocket 握手成功!")
                return resp["payload"]
            else:
                error = resp.get("error")
                logger.error(f"❌ 握手失败: {error}")
                raise Exception(f"Connect failed: {error}")
                
        except Exception as e:
            logger.error(f"❌ 连接异常: {e}")
            if self.ws:
                await self.ws.close()
            raise

    async def send(self, method: str, params: dict):
        req_id = str(uuid.uuid4())
        self.pending[req_id] = asyncio.Future()
        await self.ws.send(json.dumps({"type": "req", "id": req_id, "method": method, "params": params}))
        return await asyncio.wait_for(self.pending[req_id], timeout=30)

    async def listen(self):
        try:
            async for msg in self.ws:
                data = json.loads(msg)
                if data.get("type") == "res" and data.get("id") in self.pending:
                    self.pending[data["id"]].set_result(data)
                elif data.get("type") == "event":
                    logger.info(f"📡 [{data['event']}] {json.dumps(data.get('payload'), ensure_ascii=False)[:120]}...")
        except websockets.exceptions.ConnectionClosed:
            logger.warning("🔌 连接已断开")

    async def close(self):
        if self.ws:
            await self.ws.close()


async def test_ws():
    client = OpenClawWSClient(ws_url='ws://127.0.0.1:18789', auth_token='aa77e05531fa4da9c57bc54f30c92011eef5b6135df11985')
    try:
        await client.connect()
        listener = asyncio.create_task(client.listen())
        res = await client.send('chat.send', {'sessionKey': 'main', 'text': '/subagents spawn --task hello --mode run --label py-ws', 'deliver': False})
        logger.info(f'Response: {res}')
        await asyncio.sleep(3)
        listener.cancel()
    except Exception as e:
        logger.error(f'Failed: {e}')
    finally:
        await client.close()

if __name__ == '__main__':
    asyncio.run(test_ws())
