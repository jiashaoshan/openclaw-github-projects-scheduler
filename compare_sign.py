#!/usr/bin/env python3
"""
比较 Python 和 Node.js 的签名
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

# 相同的 payload
payload = "v3|3c45559fa664890d6c970fcdb6c279bd67a2c5e785ed643b003685925bfbc530|gateway-client|backend|operator|operator.admin|1776775795780|aa77e05531fa4da9c57bc54f30c92011eef5b6135df11985|658e72b3-4a61-4c8a-aebc-f97a85cdd093|macos"

print(f"Payload: {payload}")
print()

# Python 签名
private_key = serialization.load_pem_private_key(
    device["privateKeyPem"].encode(),
    password=None
)
signature = private_key.sign(payload.encode())
sig_b64 = base64.b64encode(signature).decode()
sig_b64url_python = sig_b64.replace("+", "-").replace("/", "_").rstrip("=")

print(f"Python signature: {sig_b64url_python}")

# Node.js 签名
result = subprocess.run(
    ["node", "test_complete.js"],
    capture_output=True,
    text=True
)

# 提取 Node.js 签名
for line in result.stdout.split("\n"):
    if "Signature (base64url):" in line:
        sig_b64url_node = line.split(":")[1].strip()
        print(f"Node.js signature:  {sig_b64url_node}")
        print(f"Match: {sig_b64url_python == sig_b64url_node}")
        break

# 也测试公钥
public_key = serialization.load_pem_public_key(device["publicKeyPem"].encode())
public_key_bytes = public_key.public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw
)
print(f"\nPython raw public key (base64): {base64.b64encode(public_key_bytes).decode()}")

# 验证 Python 签名
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
try:
    public_key.verify(signature, payload.encode())
    print("Python signature valid: True")
except Exception as e:
    print(f"Python signature valid: False - {e}")
