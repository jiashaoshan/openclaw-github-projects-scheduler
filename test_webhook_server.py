#!/usr/bin/env python3
"""
简单的 Webhook 测试服务器
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """处理 GET 请求 - 健康检查"""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "ok",
            "time": datetime.now().isoformat(),
            "message": "Webhook server is running"
        }).encode())
    
    def do_POST(self):
        """处理 POST 请求 - Webhook"""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        print(f"\n{'='*60}")
        print(f"📥 收到 Webhook 请求")
        print(f"{'='*60}")
        print(f"路径: {self.path}")
        print(f"时间: {datetime.now().isoformat()}")
        
        try:
            payload = json.loads(post_data)
            print(f"\n请求体:")
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "received",
                "time": datetime.now().isoformat()
            }).encode())
            
        except Exception as e:
            print(f"\n❌ 错误: {e}")
            self.send_response(400)
            self.end_headers()
    
    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    
    server = HTTPServer(('0.0.0.0', args.port), WebhookHandler)
    
    print(f"\n{'='*60}")
    print(f"🌐 Webhook 测试服务器已启动")
    print(f"{'='*60}")
    print(f"监听地址: http://0.0.0.0:{args.port}")
    print(f"外网地址: http://114.251.149.194:{args.port}")
    print(f"\n测试命令:")
    print(f"  curl http://114.251.149.194:{args.port}")
    print(f"\n按 Ctrl+C 停止")
    print(f"{'='*60}\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n🛑 服务器已停止")


if __name__ == "__main__":
    main()
