"""dianping真题讨论区全量采集 v2
核心优化：批量签名翻页请求（每批30页一次exe），5并发请求
题目队列 → 每批签30个当前待翻页项 → 请求 → hasMore的放回队列 → 直到全空
进度: progress.json 每批写，partial.json 每10批写
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
HOST = 'dianping-v2.kakamobi.com'
PATH = '/api/open/dianping/list.htm'
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

def fetch_page(url):
    try:
        return h.fetch_json(url, timeout=20)
    except Exception:
        return None

def harvest_all(topics, resume=True):
    total = len(topics)
    # 数据: topic -> {comments:[], cursor, hasMore}
    data = {}
    if resume and (OUT/'partial.json').exists():
        try:
            data = json.load(open(OUT/'partial.json', encoding='utf8'))
            print(f'续传: 已有 {len(data)} 题')
        except Exception:
            data = {}
    # 待翻页队列: [topic, ...]，初始所有未采完的题
    queue = []
    for t in topics:
        tstr = str(t)
        if tstr in data:
            # 已有数据的题，若还有更多则续翻
            if data[tstr].get('hasMore') and data[tstr].get('cursor'):
                queue.append(tstr)
        else:
            data[tstr] = {'comments':[], 'cursor':False, 'hasMore':True, 'pages':0}
            queue.append(tstr)
    print(f'待翻页 {len(queue)} 题，共{total}', flush=True)
    # 批次处理: 每批从队列取≤30项签名+请求
    n_batch = 0
    total_comments = sum(len(v.get('comments',[])) for v in data.values())
    while queue:
        batch_topics = queue[-CHUNK:]
        queue = queue[:-CHUNK]
        # 为每个topic构造当前页请求（cursor用各自当前值）
        reqs = []
        for t in batch_topics:
            item = data[t]
            biz = {'placeToken':PLACE_TOKEN,'topic':t,'cursor':item.get('cursor',False),'_r':h.gen_r(1)}
            reqs.append({'host':HOST,'path':PATH,'biz':biz})
        try:
            outs = sign_batch(reqs)
        except Exception as e:
            print(f'  批{n_batch} 签名失败: {str(e)[:80]}', flush=True)
            # 签名失败整批回队尾
            queue.extend(batch_topics)
            n_batch += 1
            time.sleep(2)
            continue
        # 5并发请求
        results = {}
        with ThreadPoolExecutor(max_workers=CONC) as ex:
            futs = {ex.submit(fetch_page, out.get('fullUrl','') if out.get('ok') else ''): t for t, out in zip(batch_topics, outs)}
            for f in futs:
                results[futs[f]] = f.result()
                time.sleep(SLEEP)
        # 处理结果
        for t, d in results.items():
            if d is None or not isinstance(d, dict):
                queue.append(t)   # 失败重试
                continue
            items = d.get('itemList',[])
            if items:
                data[t]['comments'].extend(items)
            data[t]['pages'] = data[t].get('pages',0) + 1
            # 最多翻5页, 或服务端说没有更多, 则完成
            if data[t]['pages'] >= 5 or not d.get('hasMore'):
                data[t]['hasMore'] = False
            else:
                data[t]['cursor'] = d.get('cursor')
                data[t]['hasMore'] = True
                queue.append(t)
        n_batch += 1
        # 每批写progress，每10批写partial
        done = sum(1 for v in data.values() if not v.get('hasMore'))
        total_comments = sum(len(v.get('comments',[])) for v in data.values())
        (OUT/'progress.json').write_text(json.dumps({'done':done,'total':total,'comments':total_comments}, ensure_ascii=False), encoding='utf8')
        if n_batch % 10 == 0:
            (OUT/'partial.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')
            print(f'  进度: {done}/{total} 题完成, 共{total_comments}评论, 队列{len(queue)}', flush=True)
    # 最终保存：压缩为 topic->[comments]
    final = {t: v['comments'] for t, v in data.items()}
    (OUT/'all-dianping.json').write_text(json.dumps(final, ensure_ascii=False, indent=1), encoding='utf8')
    n_with = sum(1 for v in final.values() if v)
    n_all = sum(len(v) for v in final.values())
    print(f'完成: {total} 题, 有评论{n_with}, 总评论{n_all}', flush=True)

if __name__ == '__main__':
    d = json.load(open(LIVE_ROOT/'data'/'car'/'questions.json', encoding='utf8'))
    topics = [str(q['question_id']) for q in d]
    print(f'car 库 {len(topics)} 题，开始 dianping v2 采集', flush=True)
    harvest_all(topics)
