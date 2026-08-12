"""VIP解析全量采集：car库6406题 artfulDetail + concise
关键：sceneCode=101（顺序练习），questionList=单题号
并发防风控：批量签名（一次exe签N题），请求5并发 + 每请求0.2s间隔，分批保存
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
OUT = LIVE_ROOT/'harvested'/'vip-explain'
OUT.mkdir(parents=True, exist_ok=True)
CHUNK = 30   # 每批签名30题
CONC = 5     # 并发数
SLEEP = 0.2  # 每请求间隔（并发下保持总QPS ≈ 5/秒）

def sign_batch(reqs):
    """批量签名：一次exe签一批"""
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

def fetch_one(q, out):
    """单题抓取（线程内执行，含降速间隔）"""
    if not out.get('ok'):
        return q, 'fail'
    try:
        d = h.fetch_json(out.get('fullUrl',''), timeout=20)
    except Exception:
        d = None
    if d is None:
        return q, 'fail'
    items = d.get('itemList',[]) if isinstance(d,dict) else []
    if items:
        return q, ('ok', items[0])
    return q, 'none'   # 该题无VIP解析，也算处理

def harvest_all(qids, resume=True):
    """全量拉VIP解析（5并发）"""
    total = len(qids)
    all_items = {}
    if resume and (OUT/'partial.json').exists():
        try:
            all_items = json.load(open(OUT/'partial.json', encoding='utf8'))
            print(f'续传: 已有 {len(all_items)} 题')
        except Exception:
            all_items = {}
    todo = [q for q in qids if q not in all_items]
    print(f'待拉 {len(todo)} / 共{total}')
    got = sum(1 for v in all_items.values() if v)
    failed = len(all_items) - got
    # 分批：签名一批（30题） + 5并发请求
    n_batch = 0
    for i in range(0, len(todo), CHUNK):
        batch = todo[i:i+CHUNK]
        reqs = [{'host':'jk-tiku.kakamobi.cn','path':'/api/open/vip/question-explain.htm',
                 'biz':{'carType':'car','kemu':'1','sceneCode':'101','questionList':q,'_r':h.gen_r(1)}} for q in batch]
        try:
            outs = sign_batch(reqs)
        except Exception as e:
            print(f'  批{i//CHUNK} 签名失败: {str(e)[:80]}'); failed += len(batch); continue
        # 5并发请求，每请求间0.2s
        results = {}
        with ThreadPoolExecutor(max_workers=CONC) as ex:
            futs = {ex.submit(fetch_one, q, out): q for q, out in zip(batch, outs)}
            for f in futs:
                q, res = f.result()
                if res == 'fail':
                    results[q] = 'fail'
                elif res == 'none':
                    results[q] = 'none'
                else:
                    results[q] = res[1]
                time.sleep(SLEEP)
        for q, res in results.items():
            if res == 'fail':
                failed += 1
            else:
                all_items[q] = None if res == 'none' else res
                got += 1
        n_batch += 1
        # 每5批存一次（进度条刷新快一点）
        if n_batch % 5 == 0:
            (OUT/'progress.json').write_text(json.dumps({'got':got,'failed':failed,'total':total}, ensure_ascii=False), encoding='utf8')
            (OUT/'partial.json').write_text(json.dumps(all_items, ensure_ascii=False), encoding='utf8')
            print(f'  进度: {got+failed}/{total}, 成功{got}, 失败{failed}')
    # 最终保存
    (OUT/'all-vip-explain.json').write_text(json.dumps(all_items, ensure_ascii=False, indent=1), encoding='utf8')
    print(f'完成: {got} 题, {failed} 失败, 共{total}')

if __name__ == '__main__':
    # car 库全部题号
    d = json.load(open(LIVE_ROOT/'data'/'car'/'questions.json', encoding='utf8'))
    qids = [str(q['question_id']) for q in d]
    print(f'car 库 {len(qids)} 题，开始 VIP 解析采集')
    harvest_all(qids)
