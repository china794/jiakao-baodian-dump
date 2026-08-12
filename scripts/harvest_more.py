"""采集第二批未拉端点（无登录能拉的）：
  - 考试项目/汽车品牌（全国城市 × carType）
  - route-video 全国各城市
  - FAQ 全状态/路线
  - 三力测试题列表（分页）
  - 交通图标、课件（已有，但补全）
  - app-db 版本清单
"""
import importlib.util, json, sys, time
from pathlib import Path
LIVE_ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("h", LIVE_ROOT/"scripts"/"harvest_api.py")
h = importlib.util.module_from_spec(spec); sys.argv=["x"]; spec.loader.exec_module(h)
sign_url, fetch_json = h.sign_url, h.fetch_json

# 33 车型
CAR = h.KNOWN_CAR_TYPES

def save(g, n, d):
    o = LIVE_ROOT/"harvested"/g; o.mkdir(parents=True, exist_ok=True)
    (o/f"{n}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf8")

def harvest_car_brands():
    merged = {}
    for ct in sorted(CAR):
        for km in ["1","4"]:
            url = sign_url("panda.kakamobi.cn","/api/open/exam-project/get-car-brand-list.htm",
                           {"kemu":km,"tiku":ct}, want_r=True)
            d = fetch_json(url, timeout=15)
            if d is None: continue
            items = d.get("itemList", [])
            if items:
                merged[f"{ct}/{km}"] = {"count":len(items), "itemList":items}
                print(f"  [{ct}/{km}] {len(items)} 品牌")
            time.sleep(0.2)
    save("exam-project","all-car-brands", merged)
    print(f"[car-brands] 保存 {len(merged)} 组合")

def harvest_route_video(city_codes):
    """全国城市：先探测 area-list 确定哪些城市有数据，再深采 place-list/list-data"""
    # 阶段1：全部城市 area-list 探测（快），跳过空城市
    cities_with_data = []
    all_areas = {}
    for cc in city_codes:
        u = sign_url("panda.kakamobi.cn","/api/open/route-video/area-list.htm",{"cityCode":cc},want_r=True)
        d = fetch_json(u, timeout=15)
        if d is None:
            continue
        items = d.get("itemList") if isinstance(d, dict) else []
        if not items:
            continue
        all_areas[cc] = items
        cities_with_data.append(cc)
    print(f"[探测] 321城市，{len(cities_with_data)} 个有路线视频数据")
    save("route-video","area-map", all_areas)

    # 阶段2：只对有数据的城市深采
    all_places, all_data = {}, {}
    for cc in cities_with_data:
        areas = all_areas[cc]
        for a in areas:
            area_code = str(a.get("areaCode"))
            key = f"{cc}/{area_code}"
            u2 = sign_url("panda.kakamobi.cn","/api/open/route-video/place-list.htm",
                          {"cityCode":cc,"areaCode":area_code},want_r=True)
            d2 = fetch_json(u2, timeout=15)
            places = (d2 or {}).get("itemList", [])
            all_places[key] = places
            for pl in places:
                pk = f"{cc}/{pl.get('id')}"
                u3 = sign_url("panda.kakamobi.cn","/api/open/route-video/list-data.htm",
                              {"cityCode":cc,"placeId":pl.get("id"),"version":""},want_r=True)
                d3 = fetch_json(u3, timeout=15)
                if d3 is not None:
                    all_data[pk] = d3
                time.sleep(0.2)
        n_places = sum(len(v) for k,v in all_places.items() if k.startswith(cc+"/"))
        print(f"  {cc}: {len(areas)} 地区, {n_places} 考场")
    save("route-video","all-areas", all_areas)
    save("route-video","all-places", all_places)
    save("route-video","all-data", all_data)
    print(f"[route-video] {len(all_areas)} 城市, {len(all_places)} 考场, {len(all_data)} 路线")

def harvest_faq():
    merged = {}
    for route in ["1","2","3"]:
        for place in ["1","2","3"]:
            u = sign_url("jiakao-misc.kakamobi.cn","/api/open/faq/list.htm",
                         {"kemu":3,"status":2,"routeId":route,"placeId":place},want_r=True)
            d = fetch_json(u, timeout=15)
            if d is None: continue
            if isinstance(d, list):
                items = d
            elif isinstance(d, dict):
                items = d.get("itemList", [])
            else:
                items = []
            if items:
                merged[f"r{route}p{place}"] = {"routeId":route,"placeId":place,"count":len(items),"itemList":items}
                print(f"  route{route} place{place}: {len(items)}")
            time.sleep(0.2)
    save("misc","faq-all", merged)
    print(f"[faq] {len(merged)} 组合")

def harvest_sanli():
    merged = {}
    for cur in [0,1,2,3]:
        u = sign_url("jk-tiku.kakamobi.cn","/api/web/exam/san-li-exam-question-list.htm",
                     {"cursor":cur,"pageSize":50},want_r=True)
        d = fetch_json(u, timeout=15)
        if d is None: continue
        if isinstance(d, list):
            items = d
        elif isinstance(d, dict):
            items = d.get("itemList", [])
        else:
            items = []
        if items:
            merged[cur] = {"cursor":cur,"count":len(items),"itemList":items}
        print(f"  cursor{cur}: {len(items)}")
        time.sleep(0.2)
    save("tiku-ext","sanli-all-pages", merged)
    print(f"[sanli] {len(merged)} 页")

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "fast"
    if which in ("brands","fast"):
        harvest_car_brands()
    if which in ("faq","fast"):
        harvest_faq()
    if which in ("sanli","fast"):
        harvest_sanli()
    if which == "route":
        cities = list(json.load(open(LIVE_ROOT/"harvested"/"jiaxiao"/"all-cities.json", encoding="utf8")).keys())
        print(f"城市码 {len(cities)} 个")
        harvest_route_video(cities)
