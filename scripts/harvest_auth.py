"""登录态数据采集：重学题库 / VIP解析 / 会员端点
依赖登录态 token 文件（由签名机注入的客户端登录态），签名机 main=run.js。
"""
import json, sys, time
sys.path.insert(0, 'scripts')
import importlib.util
spec = importlib.util.spec_from_file_location('h', 'scripts/harvest_api.py')
h = importlib.util.module_from_spec(spec); sys.argv=['x']; spec.loader.exec_module(h)
sign_url, fetch_json, gen_r = h.sign_url, h.fetch_json, h.gen_r

def save(g, n, d):
    from pathlib import Path
    o = Path(__file__).resolve().parent.parent / "harvested" / g; o.mkdir(parents=True, exist_ok=True)
    (o/f'{n}.json').write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf8')

def harvest_relearn():
    """重学题库：seqnum 1/2/3 三种场景"""
    out = {}
    for seq in [1,2,3]:
        for ct in ['car']:
            u = sign_url('jk-tiku.kakamobi.cn','/api/open/relearn/question-list.htm',
                         {'carType':ct,'seqnum':seq,'sceneCode':'102','course':'kemu1','patternCode':'101','kemuStyle':1,'bizCode':'8.13.0'})
            if not u: continue
            d = fetch_json(u, timeout=25)
            if d is not None:
                out[f'{ct}/seq{seq}'] = d
                print(f'  seq{seq}: {len(d) if isinstance(d,(list,dict)) else "?"} 项')
            time.sleep(0.3)
    save('tiku-auth','relearn-all', out)
    print(f'[relearn] {len(out)} 组合')

def harvest_vip_explain():
    """VIP题目解析：用已有题号批量试"""
    out = {}
    for ct in ['car']:
        for kemu in ['1']:
            # 用 car 库已知题号测试
            for qid in ['800000','800001','800010']:
                u = sign_url('jk-tiku.kakamobi.cn','/api/open/vip/question-explain.htm',
                             {'carType':ct,'kemu':kemu,'sceneCode':'kemu1','questionList':[qid]})
                if not u: continue
                d = fetch_json(u, timeout=25)
                if d is not None:
                    out[f'{ct}/{kemu}/{qid}'] = d
                    print(f'  {qid}: {json.dumps(d,ensure_ascii=False)[:120]}')
                time.sleep(0.3)
    save('tiku-auth','vip-explain-sample', out)
    print(f'[vip-explain] {len(out)} 条')

def harvest_member():
    """会员端点：身份/权限/徽章"""
    out = {}
    eps = [
        ('sirius.kakamobi.cn','/api/open/vip-level-info/get.htm',{'carType':'car','sceneCode':'kemu1'}),
        ('pony.kakamobi.cn','/api/open/user-member-identity/get-user-identity.htm',{'carType':'car','sceneCode':'kemu1'}),
        ('pony.kakamobi.cn','/api/open/permission/has-permissions.htm',{'permissions':'vip','needValidate':True}),
        ('pony.kakamobi.cn','/api/open/vip-badge/vip-badges.htm',{'carType':'car','sceneCode':'kemu1'}),
        ('squirrel.kakamobi.cn','/api/open/order/get-order-status.htm',{'orderNos':'1'}),
    ]
    for host,path,args in eps:
        u = sign_url(host,path,args)
        if not u: continue
        d = fetch_json(u, timeout=25)
        if d is not None:
            name = path.rstrip('.htm').split('/')[-1]
            out[name] = d
            print(f'  {name}: {json.dumps(d,ensure_ascii=False)[:150]}')
        time.sleep(0.3)
    save('member','auth-all', out)
    print(f'[member] {len(out)} 端点')

if __name__ == '__main__':
    which = sys.argv[1] if len(sys.argv)>1 else 'all'
    if which in ('all','relearn'): harvest_relearn()
    if which in ('all','vip'): harvest_vip_explain()
    if which in ('all','member'): harvest_member()
    print('完成')
