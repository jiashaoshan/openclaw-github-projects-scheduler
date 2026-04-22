#!/usr/bin/env node
/**
 * V3 Payload 签名 - 使用 Node.js crypto
 */

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

// 加载设备身份
const deviceFile = path.join(process.env.HOME, '.openclaw', 'identity', 'device.json');
const device = JSON.parse(fs.readFileSync(deviceFile, 'utf8'));

// 获取参数
const payload = process.argv[2];
if (!payload) {
    console.error('Usage: node sign_v3.js <payload>');
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
