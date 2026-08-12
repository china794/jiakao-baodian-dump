"""全国 route-video 批量采集：利用 run.js 批量签名模式，一次启动 exe 签多个请求。

流程：
  阶段1 探测：321 城市 area-list → 有数据的城市
  阶段2 深采：有数据的城市 → area place-list → place detail list-data
全程复用 sign_batch() 批量签名（chunk 每次启动 exe 签一批）。

用法：
  python scripts/route_batch.py          # 跑全国
  python scripts/route_batch.py probe    # 只探测
  python scripts/route_batch.py city 110000   # 只深采某城市
"""
import json, sys, time, subprocess, threading
from pathlib import Path

LIVE_ROOT = Path(__file__).resolve().parent.parent
PARAMS_FILE = Path(r"D:\Users\lenovo\AppData\Local\驾考宝典\sign_runner\params.json")
RESULT_FILE = Path(r"D:\Users\lenovo\AppData\Local\驾考宝典\sign_runner\result.json")
EXE = Path(r"D:\Users\lenovo\AppData\Local\驾考宝典\驾考宝典.exe")
JIAKAO_ROOT = Path(r"D:\Users\lenovo\AppData\Local\驾考宝典")

# 复用 sync_all 的 HTTP 工具
import importlib.util, sys as _sys
spec = importlib.util.spec_from_file_location("sync_all", LIVE_ROOT/"scripts"/"sync_all.py")
sync = importlib.util.module_from_spec(spec); _sys.argv=["x"]; spec.loader.exec_module(sync)
get_json = sync.get_json

SIGN_LOCK = threading.Lock()

def gen_r(e=1) -> str:
    import random as _rnd
    n = str(abs(int((time.time()*1e3)*_rnd.random()*1e4)))
    t = sum(int(c) for c in n) + len(n)
    return f"{e}{n}{str(t).zfill(3)}"

def sign_batch(reqs) -> list:
    """批量签名：一次启动 exe 签一批请求，返回结果列表。reqs: [{host,path,biz,extra}]"""
    if not reqs:
        return []
    with SIGN_LOCK:
        PARAMS_FILE.write_text(json.dumps({"mode":"batch","reqs":reqs}, ensure_ascii=False), encoding="utf8")
        RESULT_FILE.unlink(missing_ok=True)
        proc = subprocess.Popen([str(EXE)], cwd=str(JIAKAO_ROOT), creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.time() + 30
        while time.time() < deadline:
            if RESULT_FILE.exists():
                break
            time.sleep(0.2)
        try: proc.terminate()
        except Exception: pass
        time.sleep(0.3)
        try:
            if proc.poll() is None: proc.kill()
        except Exception: pass
        if not RESULT_FILE.exists():
            tail = (JIAKAO_ROOT/"sign_runner_out.txt").read_text(encoding="utf8", errors="replace")[-500:] \
                if (JIAKAO_ROOT/"sign_runner_out.txt").exists() else ""
            raise RuntimeError(f"批量签名失败（无 result.json）\n{tail}")
        result = json.loads(RESULT_FILE.read_text(encoding="utf8"))
        if not result.get("ok"):
            raise RuntimeError(f"批量签名失败: {result.get('error')}")
        outs = result.get("batch", [])
        if len(outs) != len(reqs):
            raise RuntimeError(f"批量签名数量不匹配: 请求{len(reqs)} 结果{len(outs)}")
        return outs

def sign_url_batch(reqs, chunk=50) -> list:
    """把 [(host,path,biz)] 转成批量签名请求，返回 [(url, meta)]，url 为 None 表示失败"""
    built = []
    # 构造请求时附加 _r
    reqs2 = []
    for host, path, biz in reqs:
        b = dict(biz or {})
        b.setdefault("_r", gen_r(1))
        reqs2.append({"host":host, "path":path, "biz":b})
    for i in range(0, len(reqs2), chunk):
        chunk_reqs = reqs2[i:i+chunk]
        outs = sign_batch(chunk_reqs)
        for j, out in enumerate(outs):
            if out.get("ok"):
                built.append((out.get("fullUrl"), chunk_reqs[j]))
            else:
                built.append((None, chunk_reqs[j]))
    return built

def save(g, n, d):
    o = LIVE_ROOT/"harvested"/g; o.mkdir(parents=True, exist_ok=True)
    (o/f"{n}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf8")

def probe_cities(city_codes):
    """阶段1：全部城市 area-list 探测"""
    reqs = [("panda.kakamobi.cn","/api/open/route-video/area-list.htm",{"cityCode":cc}) for cc in city_codes]
    results = sign_url_batch(reqs)
    all_areas, cities_with_data = {}, []
    for (cc, _req), (url, _r) in zip(zip(city_codes, reqs), results):
        if not url:
            print(f"  签名失败 {cc}")
            continue
        try:
            d = get_json(url, timeout=15)
        except Exception as e:
            print(f"  {cc} 请求失败: {str(e)[:60]}")
            continue
        items = d.get("itemList") if isinstance(d, dict) else []
        if items:
            all_areas[cc] = items
            cities_with_data.append(cc)
    print(f"[探测] {len(city_codes)} 城市, {len(cities_with_data)} 个有数据")
    save("route-video","area-map", all_areas)
    return all_areas, cities_with_data

def deep_cities(all_areas, cities_with_data):
    """阶段2：对有数据的城市深采"""
    all_places, all_data = {}, {}
    for cc in cities_with_data:
        areas = all_areas[cc]
        # place-list 批量
        reqs = [("panda.kakamobi.cn","/api/open/route-video/place-list.htm",
                 {"cityCode":cc,"areaCode":str(a.get("areaCode"))}) for a in areas]
        pres = sign_url_batch(reqs)
        for (a, _r), (url, _req) in zip(zip(areas, reqs), pres):
            area_code = str(a.get("areaCode"))
            key = f"{cc}/{area_code}"
            if not url:
                all_places[key] = []
                continue
            try:
                d = get_json(url, timeout=15)
            except Exception:
                all_places[key] = []
                continue
            places = d.get("itemList") if isinstance(d, dict) else []
            all_places[key] = places
            time.sleep(0.05)
        # list-data 批量
        place_ids = []
        for a in areas:
            area_code = str(a.get("areaCode"))
            for pl in all_places.get(f"{cc}/{area_code}", []):
                place_ids.append((pl.get("id"), pl))
        reqs2 = [("panda.kakamobi.cn","/api/open/route-video/list-data.htm",
                  {"cityCode":cc,"placeId":str(pid),"version":""}) for pid, _ in place_ids]
        if reqs2:
            dres = sign_url_batch(reqs2)
            for (pid, pl), (url, _req) in zip(zip(place_ids, reqs2), dres):
                pk = f"{cc}/{pid}"
                if not url:
                    continue
                try:
                    d = get_json(url, timeout=15)
                except Exception:
                    continue
                if d is not None:
                    all_data[pk] = d
                time.sleep(0.05)
        n_places = sum(len(v) for k, v in all_places.items() if k.startswith(cc+"/"))
        print(f"  {cc}: {len(areas)} 地区, {n_places} 考场, data {sum(1 for k in all_data if k.startswith(cc+'/'))}")
        save("route-video","all-areas", all_areas)
        save("route-video","all-places", all_places)
        save("route-video","all-data", all_data)
    print(f"[route-video] {len(all_areas)} 城市, {len(all_places)} 考场, {len(all_data)} 路线")
    save("route-video","all-areas", all_areas)
    save("route-video","all-places", all_places)
    save("route-video","all-data", all_data)

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    cities = list(json.load(open(LIVE_ROOT/"harvested"/"jiaxiao"/"all-cities.json", encoding="utf8")).keys())
    print(f"城市码 {len(cities)} 个")
    # 支持已存在的 area-map 断点续采
    area_map_file = LIVE_ROOT/"harvested"/"route-video"/"area-map.json"
    if which in ("all","probe"):
        all_areas, cities_with_data = probe_cities(cities)
    else:
        all_areas = json.load(open(area_map_file, encoding="utf8")) if area_map_file.exists() else {}
        cities_with_data = list(all_areas.keys())
    if which in ("all","deep"):
        deep_cities(all_areas, cities_with_data)
