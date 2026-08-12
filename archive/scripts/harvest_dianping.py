"""dianping真题讨论区全量采集
topic=题号枚举(6406题) × cursor翻页(直到hasMore=false)
5并发+0.2s间隔，断点续传，每5批存盘
产物: harvested/dianping/all-dianping.json {topic: [评论...]}
"""
import json, sys, time, subprocess, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, 'scripts')
import importlib.util
spec = importlib.util.spec_from_file_location('h', 'scripts/harvest_api.py')
h = importlib.util.module_from_spec(spec); sys.argv=['x']; spec.loader.exec_module(h)

LIVE_ROOT = Path(__file__).resolve().parent.parent
PARAMS = Path(r'D:\Users\lenovo\AppData\Local\驾考宝典\sign_runner\params.json')
RESULT = Path(r'D:\Users\lenovo\AppData\Local\驾考宝典\sign_runner\result.json')
OUT = LIVE_ROOT/'harvested'/'dianping'
OUT.mkdir(parents=True, exist_ok=True)
PLACE_TOKEN = '5bee2e55901b4de5b15b735eba3056fa'
CHUNK = 30   # 每批30题
CONC = 5     # 并发
SLEEP = 0.2  # 间隔

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
    try:
        if proc.poll() is None: proc.kill()
    except: pass
    if not RESULT.exists():
        raise RuntimeError('批量签名失败（无result.json）')
    r = json.loads(RESULT.read_text(encoding='utf8'))
    if not r.get('ok'): raise RuntimeError(f'批量签名失败: {r.get("error")}')
    return r.get('batch',[])

def fetch_one(topic):
    """拉一题的完整评论列表（含翻页）"""
    comments = []
    cursor = False
    pages = 0
    while True:
        biz = {'placeToken':PLACE_TOKEN,'topic':topic,'cursor':cursor,'_r':h.gen_r(1)}
        try:
            d = h.fetch_json(h.sign_url('dianping-v2.kakamobi.com','/api/open/dianping/list.htm',biz), timeout=20)
        except Exception:
            break
        if not isinstance(d, dict): break
        items = d.get('itemList',[])
        comments.extend(items)
        pages += 1
        if not d.get('hasMore') or not d.get('cursor'):
            break
        cursor = d.get('cursor')
        if pages > 20: break   # 防死循环
        time.sleep(SLEEP)
    return topic, comments

def harvest_all(topics, resume=True):
    total = len(topics)
    all_data = {}
    if resume and (OUT/'partial.json').exists():
        try:
            all_data = json.load(open(OUT/'partial.json', encoding='utf8'))
            print(f'续传: 已有 {len(all_data)} 题')
        except Exception:
            all_data = {}
    todo = [t for t in topics if str(t) not in all_data]
    print(f'待拉 {len(todo)} / 共{total}')
    got = len(all_data)
    n_batch = 0
    for i in range(0, len(todo), CHUNK):
        batch = todo[i:i+CHUNK]
        results = {}
        with ThreadPoolExecutor(max_workers=CONC) as ex:
            futs = [ex.submit(fetch_one, t) for t in batch]
            for f in futs:
                t, comments = f.result()
                results[t] = comments
        for t, comments in results.items():
            all_data[str(t)] = comments
        got += len(results)
        n_batch += 1
        (OUT/'progress.json').write_text(json.dumps({'got':got,'total':total}, ensure_ascii=False), encoding='utf8')
        if n_batch % 5 == 0:
            (OUT/'partial.json').write_text(json.dumps(all_data, ensure_ascii=False), encoding='utf8')
            # 进度统计
            n_with = sum(1 for v in all_data.values() if v)
            n_all = sum(len(v) for v in all_data.values())
            print(f'  进度: {got}/{total}, 有评论题{n_with}, 总评论{n_all}', flush=True)
    (OUT/'all-dianping.json').write_text(json.dumps(all_data, ensure_ascii=False, indent=1), encoding='utf8')
    n_with = sum(1 for v in all_data.values() if v)
    n_all = sum(len(v) for v in all_data.values())
    print(f'完成: {got} 题, 有评论{n_with}, 总评论{n_all}')

if __name__ == '__main__':
    # car 库全部题号
    d = json.load(open(LIVE_ROOT/'data'/'car'/'questions.json', encoding='utf8'))
    topics = [str(q['question_id']) for q in d]
    print(f'car 库 {len(topics)} 题，开始 dianping 讨论区采集', flush=True)
    harvest_all(topics)
