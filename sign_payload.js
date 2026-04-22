#!/usr/bin/env node
/**
 * 使用 Node.js crypto 模块签名 payload
 * 确保与 OpenClaw 内部实现完全一致
 */

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

// 加载设备身份
const deviceFile = path.join(process.env.HOME, '.openclaw', 'identity', 'device.json');
const device = JSON.parse(fs.readFileSync(deviceFile, 'utf8'));

// 获取 payload 从命令行参数
const payload = process.argv[2];
if (!payload) {
    console.error('Usage: node sign_payload.js <payload>');
    process.exit(1);
}

// 使用私钥签名
const privateKey = crypto.createPrivateKey(device.privateKeyPem);
const signature = crypto.sign(null, Buffer.from(payload, 'utf8'), privateKey);

// base64url 编码
const signatureBase64Url = signature.toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '');

console.log(signatureBase64Url);
