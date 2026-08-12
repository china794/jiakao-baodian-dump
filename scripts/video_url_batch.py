"""视频URL批量在线解析：shortVideoId → CDN直链videoUrl
模式:
  1. probe <svid>            单查一个shortVideoId，打印videoUrl
  2. batch                   遍历video-list-all.json所有shortVideoId，批量签名(30/批)+5并发，
                             存URL映射到 harvested/video-explain/video-urls.json
说明: videoUrl带auth_key有时效(约1天)，前端播放时应动态请求最新URL。
      本脚本是预取，验证链路可用 + 产出初始映射表。
"""
import json, sys, time, subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
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
CHUNK = 30
CONC = 5
SLEEP = 0.15

def sign_batch(reqs):
    if not reqs: return []
    PARAMS.write_text(json.dumps({'mode':'batch','reqs':reqs}, ensure_ascii=False), encoding='utf8')
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
        raise RuntimeError('批量签名失败（无result.json）')
    r = json.loads(RESULT.read_text(encoding='utf8'))
    if not r.get('ok'): raise RuntimeError(f'批量签名失败: {r.get("error")}')
    return r.get('batch',[])

def fetch_url(full_url):
    if not full_url:
        return None
    try:
        d = h.fetch_json(full_url, timeout=20)
        items = d.get('itemList',[]) if isinstance(d, dict) else []
        if items and items[0].get('videoUrl'):
            return items[0]['videoUrl']
    except Exception:
        pass
    return None

def probe(svid):
    biz = {'idList': str(svid), '_r': h.gen_r(1)}
    out = sign_batch([{'host':HOST,'path':PATH,'biz':biz}])[0]
    u = fetch_url(out.get('fullUrl','') if out.get('ok') else '')
    print(f'{svid} → {u}')

def batch_all():
    vl = json.load(open(OUT/'video-list-all.json', encoding='utf8'))
    # 提取 (svid, questionId) 列表，去重
    pairs = {}
    for it in vl['itemList']:
        for dl in it.get('dataList',[]):
            pairs[dl['shortVideoId']] = it['questionId']
    svids = list(pairs.keys())
    total = len(svids)
    print(f'共 {total} 个 shortVideoId', flush=True)
    # 续传
    urlmap = {}
    if (OUT/'video-urls.json').exists():
        try:
            urlmap = json.load(open(OUT/'video-urls.json', encoding='utf8'))
            print(f'续传: 已有 {len(urlmap)} 个', flush=True)
        except Exception:
            urlmap = {}
    todo = [s for s in svids if str(s) not in urlmap]
    print(f'待解析 {len(todo)} / {total}', flush=True)
    # 分批：签名30 + 5并发
    ok = 0
    fail = 0
    for i in range(0, len(todo), CHUNK):
        batch = todo[i:i+CHUNK]
        reqs = [{'host':HOST,'path':PATH,'biz':{'idList':str(s),'_r':h.gen_r(1)}} for s in batch]
        try:
            outs = sign_batch(reqs)
        except Exception as e:
            print(f'  批{i//CHUNK} 签名失败: {str(e)[:80]}', flush=True)
            fail += len(batch)
            time.sleep(2)
            continue
        # 5并发拉URL
        results = {}
        with ThreadPoolExecutor(max_workers=CONC) as ex:
            futs = {ex.submit(fetch_url, out.get('fullUrl','') if out.get('ok') else ''): s
                    for s, out in zip(batch, outs)}
            for f in futs:
                results[futs[f]] = f.result()
                time.sleep(SLEEP)
        for s, u in results.items():
            if u:
                urlmap[str(s)] = u
                ok += 1
            else:
                fail += 1
        # 每10批存一次
        if (i//CHUNK) % 10 == 9:
            (OUT/'video-urls.json').write_text(json.dumps(urlmap, ensure_ascii=False, indent=1), encoding='utf8')
            print(f'  进度: {ok+fail}/{total} 成功{ok} 失败{fail}', flush=True)
    # 最终：svid -> {questionId, videoUrl}
    final = {}
    for s in svids:
        su = urlmap.get(str(s))
        if su:
            final[str(s)] = {'questionId': pairs[s], 'videoUrl': su}
    (OUT/'video-urls.json').write_text(json.dumps(final, ensure_ascii=False, indent=1), encoding='utf8')
    print(f'完成: {len(final)}/{total} 个视频URL, 失败{fail}', flush=True)

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'probe':
        probe(int(sys.argv[2]))
    else:
        batch_all()
