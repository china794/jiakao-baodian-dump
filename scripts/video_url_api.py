"""视频URL在线解析 HTTP 服务（auth_key 5分钟过期，必须实时拉）
用法: python scripts/video_url_api.py [端口]   默认 8790
接口:
  GET /api/video?svid=<shortVideoId>        → {"svid":.., "videoUrl":"http://...mp4?auth_key=..."}
  GET /api/video/by-question?qid=<questionId> → 从video-list-all.json查svid再解析
前端每次播放调用一次，拿最新auth_key直链。签名机保持 sign_runner/run.js 常驻。
"""
import json, sys, time, subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
sys.path.insert(0, 'scripts')
import importlib.util
spec = importlib.util.spec_from_file_location('h', 'scripts/harvest_api.py')
h = importlib.util.module_from_spec(spec); sys.argv=['x']; spec.loader.exec_module(h)

LIVE_ROOT = Path(__file__).resolve().parent.parent
PARAMS = Path(r'D:\Users\lenovo\AppData\Local\驾考宝典\sign_runner\params.json')
RESULT = Path(r'D:\Users\lenovo\AppData\Local\驾考宝典\sign_runner\result.json')
VIDEO_LIST = LIVE_ROOT/'harvested'/'video-explain'/'video-list-all.json'
HOST = 'short-video.kakamobi.cn'
PATH = '/api/open/video/question-origin-video-detail.htm'
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8790

# 缓存 svid→questionId 反向映射
_QMAP = None
def qmap():
    global _QMAP
    if _QMAP is None:
        _QMAP = {}
        vl = json.load(open(VIDEO_LIST, encoding='utf8'))
        for it in vl['itemList']:
            qid = it['questionId']
            for dl in it.get('dataList', []):
                _QMAP[qid] = dl['shortVideoId']
    return _QMAP

def sign_single(svid):
    biz = {'idList': str(svid), '_r': h.gen_r(1)}
    PARAMS.write_text(json.dumps({'mode':'batch','reqs':[{'host':HOST,'path':PATH,'biz':biz}]}, ensure_ascii=False), encoding='utf8')
    RESULT.unlink(missing_ok=True)
    proc = subprocess.Popen([str(h.EXE)], cwd=str(h.JIAKAO_ROOT), creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.time()+40
    while time.time()<deadline:
        if RESULT.exists(): break
        time.sleep(0.2)
    try: proc.terminate()
    except: pass
    time.sleep(0.3)
    if not RESULT.exists(): return None
    r = json.loads(RESULT.read_text(encoding='utf8'))
    if not r.get('ok') or not r.get('batch'): return None
    out = r['batch'][0]
    if not out.get('ok') or not out.get('fullUrl'): return None
    try:
        d = h.fetch_json(out['fullUrl'], timeout=20)
        items = d.get('itemList',[]) if isinstance(d, dict) else []
        if items and items[0].get('videoUrl'):
            return items[0]['videoUrl']
    except Exception:
        pass
    return None

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            from urllib.parse import urlparse, parse_qs
            pr = urlparse(self.path)
            qs = parse_qs(pr.query)
            svid = None
            if pr.path == '/api/video' and 'svid' in qs:
                svid = qs['svid'][0]
            elif pr.path == '/api/video/by-question' and 'qid' in qs:
                svid = qmap().get(int(qs['qid'][0]))
            if svid is None:
                self._json({'ok': False, 'error': '缺少svid/qid'}, 400)
                return
            url = sign_single(int(svid))
            if not url:
                self._json({'ok': False, 'error': '解析失败'}, 500)
                return
            self._json({'ok': True, 'svid': int(svid), 'videoUrl': url})
        except Exception as e:
            self._json({'ok': False, 'error': str(e)}, 500)
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf8')
        self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def log_message(self,*a): pass

if __name__ == '__main__':
    print(f'视频URL在线解析: http://127.0.0.1:{PORT}/api/video?svid=... 或 ?qid=...')
    HTTPServer(('127.0.0.1',PORT), H).serve_forever()
