"""探测新端点：cheyouquan分享配置 + dianping点评
只在VIP采集间隙单请求探测，不抢签名机文件
"""
import json, sys, time, subprocess, threading
from pathlib import Path
sys.path.insert(0, 'scripts')
import importlib.util
spec = importlib.util.spec_from_file_location('h', 'scripts/harvest_api.py')
h = importlib.util.module_from_spec(spec); sys.argv=['x']; spec.loader.exec_module(h)

PARAMS = Path(r'D:\Users\lenovo\AppData\Local\驾考宝典\sign_runner\params.json')
RESULT = Path(r'D:\Users\lenovo\AppData\Local\驾考宝典\sign_runner\result.json')
OUT = Path(__file__).resolve().parent.parent / "harvested"

def sign_one(host, path, biz):
    PARAMS.write_text(json.dumps({'mode':'batch','reqs':[{'host':host,'path':path,'biz':biz}]}, ensure_ascii=False), encoding='utf8')
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
        return None, 'no-result'
    r = json.loads(RESULT.read_text(encoding='utf8'))
    if not r.get('ok'):
        return None, r.get('error','sign-fail')
    batch = r.get('batch',[])
    if not batch: return None, 'empty-batch'
    return batch[0].get('fullUrl'), None

def fetch(url):
    try:
        return h.fetch_json(url, timeout=20)
    except Exception as e:
        return {'err': str(e)[:120]}

probes = [
    ('cheyouquan-share-configs', 'cheyouquan.kakamobi.cn', '/api/open/business/jiakao/get-exam-share-configs.htm', {}),
    ('dianping-list', 'dianping-v2.kakamobi.com', '/api/open/dianping/list.htm', {'placeToken':'5bee2e55901b4de5b15b735eba3056fa','topic':800000,'cursor':False}),
]
for name, host, path, biz in probes:
    url, err = sign_one(host, path, biz)
    if err:
        print(f'[{name}] 签名失败: {err}')
        continue
    d = fetch(url)
    print(f'[{name}] URL={url[:100]}...')
    s = json.dumps(d, ensure_ascii=False)
    print(f'  -> {s[:400]}')
    print()
    # 存一份
    (OUT/'probe'/f'{name}.json').parent.mkdir(exist_ok=True)
    (OUT/'probe'/f'{name}.json').write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf8')
print('探测完成')
