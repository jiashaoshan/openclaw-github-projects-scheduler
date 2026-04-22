#!/usr/bin/env node
/**
 * 完整的签名测试
 */

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

// 加载设备身份
const deviceFile = path.join(process.env.HOME, '.openclaw', 'identity', 'device.json');
const device = JSON.parse(fs.readFileSync(deviceFile, 'utf8'));

// 构建与 Python 相同的 payload
const payload = "v3|3c45559fa664890d6c970fcdb6c279bd67a2c5e785ed643b003685925bfbc530|gateway-client|backend|operator|operator.admin|1776775795780|aa77e05531fa4da9c57bc54f30c92011eef5b6135df11985|658e72b3-4a61-4c8a-aebc-f97a85cdd093|macos";

console.log("Payload:", payload);

// 使用私钥签名
const privateKey = crypto.createPrivateKey(device.privateKeyPem);
const signature = crypto.sign(null, Buffer.from(payload, 'utf8'), privateKey);

// base64url 编码
const signatureBase64Url = signature.toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '');

console.log("Signature (base64url):", signatureBase64Url);

// 验证签名
const publicKey = crypto.createPublicKey(device.publicKeyPem);
const isValid = crypto.verify(null, Buffer.from(payload, 'utf8'), publicKey, signature);
console.log("Signature valid:", isValid);

// 也测试 derivePublicKeyRaw
const ED25519_SPKI_PREFIX = Buffer.from("302a300506032b6570032100", "hex");
const spki = publicKey.export({ type: "spki", format: "der" });
console.log("SPKI length:", spki.length);
console.log("SPKI prefix match:", spki.subarray(0, ED25519_SPKI_PREFIX.length).equals(ED25519_SPKI_PREFIX));
if (spki.length === ED25519_SPKI_PREFIX.length + 32) {
    const raw = spki.subarray(ED25519_SPKI_PREFIX.length);
    console.log("Raw public key (hex):", raw.toString('hex'));
    console.log("Raw public key (base64):", raw.toString('base64'));
}
