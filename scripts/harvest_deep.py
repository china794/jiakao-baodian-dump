"""深度采集：遍历全量参数，把能拉的数据全拉下来。

在 harvest_api.py（单点探测）基础上，对已确认可用的端点做全参数遍历：
  1. jiaxiao/list-city  —— 遍历全国 352 个城市码 → 全国驾校全量
  2. traffic-icon/icon-list —— 遍历全部 groupId → 全部交通图标
  3. exam-project/list —— 遍历全部 carType × kemu → 考试项目全量
  4. kejian/lecture-list —— 遍历全部 projectId → 课件讲义全量

产物归档 harvested/<group>/<name>.json（深采覆盖单点探测的结果）。
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path

LIVE_ROOT = Path(__file__).resolve().parent.parent
HARVEST_DIR = LIVE_ROOT / "harvested"

# 复用 harvest_api 的签名工具
spec = importlib.util.spec_from_file_location("h", LIVE_ROOT / "scripts" / "harvest_api.py")
h = importlib.util.module_from_spec(spec)
sys.argv = ["x"]
spec.loader.exec_module(h)
sign_url = h.sign_url
fetch_json = h.fetch_json

# 33 个已知 carType
CAR_TYPES = h.KNOWN_CAR_TYPES

# 全国城市码：从 car.db t_vp.city + t_exam_rule.areacode 挖出（352 个）
def load_city_codes() -> list[str]:
    con = sqlite3.connect(str(LIVE_ROOT / "dbs" / "car.db"))
    codes = set()
    for r in con.execute("SELECT DISTINCT city FROM t_vp WHERE city IS NOT NULL AND city != ''"):
        c = str(r[0])
        if c and c != "0":
            codes.add(c)
    for r in con.execute("SELECT DISTINCT areacode FROM t_exam_rule WHERE areacode IS NOT NULL"):
        c = str(r[0])
        if c and c != "0":
            codes.add(c)
    con.close()
    return sorted(codes)

def save(group: str, name: str, data) -> Path:
    out_dir = HARVEST_DIR / group
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{name}.json"
    out_file.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf8")
    return out_file

def harvest_jiaxiao(cities: list[str]) -> dict:
    """遍历全国城市拉驾校。
    规律（实测）：市级码（非 xx0000）→ 该市全部驾校；直辖市省码（110000等）→ 该市驾校；
    普通省码 → 0。因此遍历全部市级码 + 直辖市省码，合并去重。"""
    merged = {}
    ok = fail = 0
    # 直辖市省码（110000/120000/310000/500000 本身是市）
    direct = {"110000", "120000", "310000", "500000"}
    codes = [c for c in cities if (not c.endswith("0000")) or c in direct]
    for cc in codes:
        url = sign_url("jiaxiao.kakamobi.cn", "/api/web/v3/jiaxiao/list-city.htm",
                       {"cityCode": cc}, want_r=True)
        if not url:
            fail += 1
            continue
        data = fetch_json(url, timeout=20)
        if data is None:
            fail += 1
            continue
        item_list = data.get("itemList", [])
        merged[cc] = item_list
        ok += 1
        print(f"  {cc}: {len(item_list)} 驾校")
        time.sleep(0.25)
    out = save("jiaxiao", "all-cities", merged)

    # 合并去重 → 全国驾校全量
    seen = {}
    dup = 0
    for item_list in merged.values():
        for s in item_list:
            sid = s.get("id")
            if sid in seen:
                dup += 1
                continue
            seen[sid] = s
    out2 = save("jiaxiao", "all-schools", list(seen.values()))
    print(f"[jiaxiao] 城市码 {len(codes)} 个，成功 {ok}，失败 {fail}，"
          f"去重后全国驾校 {len(seen)} 所（去重 {dup}）-> {out2}")
    return merged

def harvest_traffic_icons() -> dict:
    """先拿 group-list 全分组，再遍历 groupId 拉全部图标。"""
    url = sign_url("panda.kakamobi.cn", "/api/open/traffic-icon/group-list.htm",
                   {"carType": "car"}, want_r=True)
    groups = fetch_json(url, timeout=20) or {}
    group_list = groups.get("itemList", [])
    print(f"[traffic-icon] 分组 {len(group_list)} 个")
    save("traffic-icon", "group-list", groups)

    all_icons = {}
    for g in group_list:
        gid = g.get("id")
        url = sign_url("panda.kakamobi.cn", "/api/open/traffic-icon/icon-list.htm",
                       {"groupId": gid, "carType": "car"}, want_r=True)
        data = fetch_json(url, timeout=20)
        if data is None:
            continue
        icons = data.get("itemList", [])
        all_icons[str(gid)] = icons
        print(f"  groupId={gid} ({g.get('name')}): {len(icons)} 图标")
        time.sleep(0.3)
    out = save("traffic-icon", "all-icons", all_icons)
    print(f"[traffic-icon] 全图标 {sum(len(v) for v in all_icons.values())} 个 -> {out}")
    return all_icons

def harvest_exam_projects(car_types: set[str]) -> dict:
    """遍历 carType × kemu 拉考试项目。"""
    kemus = ["1", "4"]  # 科目一/科目四（大部分题库只有这两个）
    merged = {}
    ok = fail = 0
    for ct in sorted(car_types):
        for km in kemus:
            url = sign_url("panda.kakamobi.cn", "/api/open/exam-project/list.htm",
                           {"kemu": km, "tiku": ct, "cursor": 0, "pageSize": 100,
                            "encodeVersion": 1}, want_r=True)
            data = fetch_json(url, timeout=20)
            if data is None:
                fail += 1
                continue
            item_list = data.get("itemList", [])
            merged[f"{ct}/{km}"] = {"kemu": km, "tiku": ct, "itemList": item_list,
                                    "count": len(item_list)}
            if item_list:
                ok += 1
                print(f"  {ct} kemu{km}: {len(item_list)} 项目")
            time.sleep(0.25)
    out = save("exam-project", "all", merged)
    total = sum(v["count"] for v in merged.values())
    print(f"[exam-project] {len(merged)} 组合，有数据 {ok}，失败 {fail}，总项目 {total} -> {out}")
    return merged

def harvest_kejian(car_types: set[str]) -> dict:
    """先拿 project-list 全部项目（kemu 1/4），再遍历 projectId 拉讲义。"""
    merged = {}
    projects_by_kemu = {}
    for km in ["1", "4"]:
        url = sign_url("panda.kakamobi.cn", "/api/open/kejian/project-list.htm",
                       {"kemu": km}, want_r=True)
        data = fetch_json(url, timeout=20)
        if data is None:
            continue
        projects = data.get("itemList", [])
        projects_by_kemu[km] = projects
        print(f"  kemu{km}: {len(projects)} 项目")
        for p in projects:
            pid = p.get("projectId")
            url2 = sign_url("panda.kakamobi.cn", "/api/open/kejian/lecture-list.htm",
                            {"projectId": pid, "kemu": km}, want_r=True)
            lec = fetch_json(url2, timeout=20)
            if lec is None:
                continue
            key = f"{km}/{pid}"
            merged[key] = lec.get("itemList", [])
            print(f"    projectId={pid} ({p.get('name','?')}): {len(lec.get('itemList',[]))} 讲义")
            time.sleep(0.25)
    out = save("kejian", "all-lectures", merged)
    print(f"[kejian] 讲义 {len(merged)} 项目 -> {out}")
    return merged

def main() -> int:
    cities = load_city_codes()
    print(f"城市码 {len(cities)} 个")
    t0 = time.time()
    harvest_jiaxiao(cities)
    harvest_traffic_icons()
    harvest_exam_projects(CAR_TYPES)
    harvest_kejian(CAR_TYPES)
    print(f"\n全部完成，耗时 {time.time()-t0:.0f}s")
    return 0

if __name__ == "__main__":
    sys.exit(main())
