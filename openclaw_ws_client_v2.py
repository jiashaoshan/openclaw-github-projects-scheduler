#!/usr/bin/env python3
"""
OpenClaw WebSocket 客户端 - 最终生产版
✅ 固定 client.mode = "cli"（已通过校验）
✅ 自动管理 Ed25519 密钥 + 持久化 device.id
✅ 正确签名 nonce，通过 DEVICE_AUTH 校验
"""

import asyncio
import json
import uuid
import websockets
import time
import base64
import hashlib
import logging
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class OpenClawWSClient:
    def __init__(self, ws_url: str, token: str = None):
        self.ws_url = ws_url
        self.ws = None
        self.pending = {}

        # 🔑 使用 OpenClaw 本地 device.json
        self.device_file = Path.home() / ".openclaw" / "identity" / "device.json"
        self.auth_file = Path.home() / ".openclaw" / "identity" / "device-auth.json"
        self.private_key, self.public_key_b64, self.device_id = self._load_device_identity()
        
        # 优先使用传入的 token，否则从 device-auth.json 加载
        if token:
            self.token = token
            logger.info(f"🔑 使用传入的 token")
        elif self.auth_file.exists():
            with open(self.auth_file) as f:
                auth_data = json.load(f)
            if "tokens" in auth_data and "operator" in auth_data["tokens"]:
                self.token = auth_data["tokens"]["operator"]["token"]
                logger.info(f"🔑 从 device-auth.json 加载 token: {self.token[:20]}...")
            else:
                self.token = None
        else:
            self.token = None
        
        logger.info(f"📱 使用设备 ID: {self.device_id}")

    def _load_device_identity(self):
        """从 OpenClaw device.json 加载设备身份"""
        if not self.device_file.exists():
            raise FileNotFoundError(f"Device identity not found: {self.device_file}")
        
        with open(self.device_file) as f:
            data = json.load(f)
        
        device_id = data["deviceId"]
        
        # 从 PEM 加载私钥
        from cryptography.hazmat.primitives import serialization
        private_key = serialization.load_pem_private_key(
            data["privateKeyPem"].encode(),
            password=None
        )
        
        # 获取原始公钥 bytes 并转为 base64url（与 OpenClaw 一致）
        public_key = private_key.public_key()
        public_key_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        # base64url 编码（无填充，替换 +/ 为 -_）
        public_key_b64 = base64.b64encode(public_key_bytes).decode()
        public_key_b64 = public_key_b64.replace("+", "-").replace("/", "_").rstrip("=")
        
        return private_key, public_key_b64, device_id

    def _build_payload_v3(self, nonce: str, signed_at_ms: int) -> str:
        """构建 V3 格式的 payload（与 OpenClaw 内部一致）"""
        # v3|deviceId|clientId|clientMode|role|scopes|signedAt|token|nonce|platform|deviceFamily
        platform = "macos"
        device_family = "python-cli"  # 与 client.deviceFamily 一致
        scopes_str = ",".join(["operator.read", "operator.admin", "operator.write", "operator.approvals", "operator.pairing"])
        # 使用 device token（从 device-auth.json 加载）
        token = self.token if self.token else ""
        
        parts = [
            "v3",
            self.device_id,
            "cli",  # client.id
            "cli",  # client.mode
            "operator",  # role
            scopes_str,
            str(signed_at_ms),
            token,
            nonce,
            platform,
            device_family
        ]
        return "|".join(parts)

    def _sign_payload(self, payload: str) -> str:
        """使用 Node.js 签名 payload（确保与 OpenClaw 一致）"""
        import subprocess
        sign_script = Path(__file__).parent / "sign_v3.js"
        result = subprocess.run(
            ["node", str(sign_script), payload],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            raise RuntimeError(f"Node.js 签名失败: {result.stderr}")
        return result.stdout.strip()

    async def connect(self):
        self.ws = await websockets.connect(self.ws_url, ping_interval=20, ping_timeout=10)

        # 1. 接收 challenge
        chal = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=5))
        if chal.get("event") != "connect.challenge":
            raise Exception(f"Expected challenge, got: {chal}")
        nonce = chal["payload"]["nonce"]
        signed_at_ms = int(time.time() * 1000)
        
        # 构建 payload 并签名
        payload = self._build_payload_v3(nonce, signed_at_ms)
        logger.info(f"📋 Payload: {payload}")
        signature = self._sign_payload(payload)
        logger.info(f"✅ Signature: {signature[:40]}...")

        # 2. 构造 connect 请求（严格匹配 "cli" 模式）
        req = {
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
                    "deviceFamily": "python-cli"  # 不能为空，至少1个字符
                },
                "role": "operator",
                "scopes": ["operator.read", "operator.admin", "operator.write", "operator.approvals", "operator.pairing"],
                "auth": {"token": self.token},  # 使用 device token（从 device-auth.json 加载）
                "device": {
                    "id": self.device_id,
                    "publicKey": self.public_key_b64,
                    "signature": signature,
                    "signedAt": signed_at_ms,
                    "nonce": nonce
                }
            }
        }

        await self.ws.send(json.dumps(req))
        resp = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=10))

        if not resp.get("ok"):
            err = resp.get("error")
            # 如果报 DEVICE_NOT_REGISTERED，需先批准设备
            if isinstance(err, dict) and err.get("code") == "DEVICE_NOT_REGISTERED":
                logger.warning("⚠️ 新设备待批准。请执行: openclaw device approve %s", self.device_id)
                raise Exception(f"Connect failed: {json.dumps(err, ensure_ascii=False, indent=2)}")
            raise Exception(f"Connect failed: {json.dumps(err, ensure_ascii=False, indent=2)}")

        logger.info("✅ WebSocket 握手成功！")
        return resp["payload"]

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


async def spawn_agent_ws(task: str, token: str = None) -> bool:
    # 使用 device token（从 device-auth.json 自动加载）
    # 如果传入了 token 则使用，否则自动从 device-auth.json 加载
    client = OpenClawWSClient(
        ws_url="ws://127.0.0.1:18789",
        token=token  # 传入 None 时会自动从 device-auth.json 加载
    )
    try:
        await client.connect()
        listener = asyncio.create_task(client.listen())

        # 通过 chat.send 间接触发子 Agent
        result = await client.send("chat.send", {
            "sessionKey": "main",
            "text": f"/subagents spawn --task \"{task}\" --mode run --label py-ws-final",
            "deliver": False
        })
        logger.info(f"🚀 Spawn 响应: {json.dumps(result, ensure_ascii=False, indent=2)}")

        await asyncio.sleep(5)
        listener.cancel()
        return True
    except Exception as e:
        logger.error(f"❌ 调用失败: {e}")
        return False
    finally:
        await client.close()


if __name__ == "__main__":
    # 不传 token，自动从 device-auth.json 加载
    asyncio.run(spawn_agent_ws(
        task="测试 WebSocket 最终版"
    ))
