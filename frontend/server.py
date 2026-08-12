"""驾考宝典数据浏览器 - 极简本地服务器
用法: python server.py [端口]   默认 8700
访问: http://127.0.0.1:8700/
"""
import http.server, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # 项目根, 这样可访问 data/ 和 harvested/
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8700
os.chdir(ROOT)

class H(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()
    def log_message(self, *a):
        pass

print(f'驾考宝典数据浏览器: http://127.0.0.1:{PORT}/')
print(f'根目录: {ROOT}')
http.server.ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()
