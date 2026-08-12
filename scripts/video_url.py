"""视频URL在线方案：shortVideoId → CDN直链videoUrl
模式:
  1. probe <id>      单查一个shortVideoId，打印videoUrl
  2. batch           遍历video-list-all.json所有shortVideoId，存URL映射到harvested/video-explain/video-urls.json
说明: videoUrl带auth_key有时效，前端播放时应动态调用(见url_api.py)，本文件是批量预取
"""
import json, sys, time, subprocess
from pathlib import Path
sys.path.insert(0, 'scripts')
import importlib.util
spec = importlib.util.spec_from_file_location('h', 'scripts/harvest_api.py')
h = importlib.util.module_from_spec(spec); sys.argv=['x']; spec.loader.exec_module(h)

LIVE_ROOT = Path(__file__).resolve().parent.parent
PARAMS = Path(r'D:\Users\lenovo\AppData\Local\驾考宝典\sign_runner\params.json')
RESULT = Path(r'D:\Users\lenovo\AppData\Local\驾考宝典\sign_runner\result.json')
OUT = LIVE_ROOT/'harvested'/'video-explain'
HOST = 'short-video.kakamobi.cn'
PATH = '/api/open/video/question-origin-video-detail.htm'

def get_url(svid):
    """单查一个shortVideoId → videoUrl"""
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
    if not RESULT.exists():
        return None
    r = json.loads(RESULT.read_text(encoding='utf8'))
    if not r.get('ok'): return None
    url = r['batch'][0]['fullUrl']
    try:
        d = h.fetch_json(url, timeout=20)
        items = d.get('itemList',[])
        if items and items[0].get('videoUrl'):
            return items[0]['videoUrl']
    except Exception:
        pass
    return None

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'probe':
        svid = int(sys.argv[2])
        u = get_url(svid)
        print(f'{svid} → {u}')
    else:
        # batch 模式
        vl = json.load(open(OUT/'video-list-all.json', encoding='utf8'))
        svids = [it['dataList'][0]['shortVideoId'] for it in vl['itemList']]
        print(f'共 {len(svids)} 个 shortVideoId')
        # 先测3个
        for svid in svids[:3]:
            u = get_url(svid)
            print(f'  {svid} → {str(u)[:100]}')
