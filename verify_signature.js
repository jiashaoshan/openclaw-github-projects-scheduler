#!/usr/bin/env node
/**
 * 验证签名是否有效
 */

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

// 加载设备身份
const deviceFile = path.join(process.env.HOME, '.openclaw', 'identity', 'device.json');
const device = JSON.parse(fs.readFileSync(deviceFile, 'utf8'));

// 获取参数
const payload = process.argv[2];
const signatureBase64Url = process.argv[3];

if (!payload || !signatureBase64Url) {
    console.error('Usage: node verify_signature.js <payload> <signature>');
    process.exit(1);
}

// base64url 解码
function base64UrlDecode(input) {
    const normalized = input.replace(/-/g, '+').replace(/_/g, '/');
    const padded = normalized + '='.repeat((4 - normalized.length % 4) % 4);
    return Buffer.from(padded, 'base64');
}

// 验证签名
const publicKey = device.publicKeyPem;
const key = crypto.createPublicKey(publicKey);

const sig = (() => {
    try {
        return base64UrlDecode(signatureBase64Url);
    } catch {
        return Buffer.from(signatureBase64Url, 'base64');
    }
})();

const isValid = crypto.verify(null, Buffer.from(payload, 'utf8'), key, sig);
console.log('Signature valid:', isValid);

// 也测试签名
const privateKey = crypto.createPrivateKey(device.privateKeyPem);
const testSig = crypto.sign(null, Buffer.from(payload, 'utf8'), privateKey);
const testSigBase64Url = testSig.toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '');

console.log('Expected signature:', testSigBase64Url);
console.log('Provided signature:', signatureBase64Url);
console.log('Match:', testSigBase64Url === signatureBase64Url);
