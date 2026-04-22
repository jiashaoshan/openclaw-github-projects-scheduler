#!/usr/bin/env python3
"""
测试签名生成和验证
"""

import json
import base64
import subprocess
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# 加载设备身份
device_file = Path.home() / ".openclaw" / "identity" / "device.json"
with open(device_file) as f:
    device = json.load(f)

# 加载私钥
private_key = serialization.load_pem_private_key(
    device["privateKeyPem"].encode(),
    password=None
)

# 加载公钥
public_key = serialization.load_pem_public_key(
    device["publicKeyPem"].encode()
)

# 测试 payload
payload = "v2|test|cli|cli|operator|operator.read,operator.write|1234567890||nonce123"

# Python 签名
signature = private_key.sign(payload.encode())
sig_b64 = base64.b64encode(signature).decode()
sig_b64url = sig_b64.replace("+", "-").replace("/", "_").rstrip("=")

print(f"Payload: {payload}")
print(f"Python signature (base64url): {sig_b64url}")

# 用 Node.js 验证
result = subprocess.run(
    ["node", "verify_signature.js", payload, sig_b64url],
    capture_output=True,
    text=True
)
print(f"\nNode.js verification:")
print(result.stdout)
if result.stderr:
    print("Errors:", result.stderr)

# 也测试用 Node.js 签名同样的 payload
result2 = subprocess.run(
    ["node", "sign_payload.js", payload],
    capture_output=True,
    text=True
)
node_sig = result2.stdout.strip()
print(f"\nNode.js signature: {node_sig}")
print(f"Match: {sig_b64url == node_sig}")
