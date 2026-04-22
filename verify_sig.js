#!/usr/bin/env node
/**
 * 验证签名
 */

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

// 加载设备身份
const deviceFile = path.join(process.env.HOME, '.openclaw', 'identity', 'device.json');
const device = JSON.parse(fs.readFileSync(deviceFile, 'utf8'));

const payload = "v3|3c45559fa664890d6c970fcdb6c279bd67a2c5e785ed643b003685925bfbc530|cli|cli|operator|operator.read,operator.write|1776779181036|aa77e05531fa4da9c57bc54f30c92011eef5b6135df11985|001a4291-0851-4db9-a616-b6a023fd1cae|macos|";
const signatureBase64Url = "Zfb1E0SitI_JCVdTKurk8d7jIV64TeTiYT3D9yAbDV6wYJ_A70Xq6IZ7tJ64t5_36d4J6IEec-DR1J0UjL9LAg";

// 解码 base64url
function base64UrlDecode(str) {
    str += new Array(5 - str.length % 4).join('=');
    return Buffer.from(str.replace(/\-/g, '+').replace(/\_/g, '/'), 'base64');
}

// 加载公钥
const publicKey = crypto.createPublicKey(device.publicKeyPem);

// 解码签名
const sig = base64UrlDecode(signatureBase64Url);

// 验证
const isValid = crypto.verify(null, Buffer.from(payload, 'utf8'), publicKey, sig);
console.log("Signature valid:", isValid);
