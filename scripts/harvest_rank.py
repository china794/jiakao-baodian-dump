"""排行榜全量采集 (ke1/ke4/zige.jiakaobaodian.com)
不需要签名, 只加 _s 随机串。遍历:
  域名: ke1(course1)/ke4(course4)/zige(资格证)
  areaScope: city(城市) / school(驾校) / province / country
  timeScope: day / week / month / all
  城市: all-cities.json 的 321 城
  school 榜: 用各城市驾校 code+name

产物: harvested/rank/all-rank.json  {key: {domain, scope, time, cityName, cityCode, schoolCode, schoolName, rankList, myRank, rankArea, dateTime}}
      harvested/rank/progress.json  {done, total, entries}
策略: 不签名的 GET 直连, 8并发, 断点续传(progress 存盘)
"""
import importlib.util, json, sys, time, urllib.parse, urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

LIVE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LIVE_ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("h", LIVE_ROOT / "scripts" / "harvest_api.py")
h = importlib.util.module_from_spec(spec); sys.argv = ["x"]; spec.loader.exec_module(h)

OUT = LIVE_ROOT / "harvested" / "rank"
OUT.mkdir(parents=True, exist_ok=True)
CITIES = json.load(open(LIVE_ROOT / "harvested" / "jiaxiao" / "all-cities.json", encoding="utf8"))

HOSTS = {
    "ke1": "ke1.jiakaobaodian.com",     # course1 (科目一)
    "ke4": "ke4.jiakaobaodian.com",     # course4 (科目四)
    "zige": "zige.jiakaobaodian.com",   # 资格证
}
PATH = "/api/open/h5/rank/list.htm"
TIME_SCOPES = ["day", "week", "month", "all"]
CONC = 8
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

def fetch_rank(host, biz):
    params = dict(getattr(h, "BASE_PARAMS", {}))
    params.update(biz)
    params["_s"] = h.gen_r(1)
    url = f"https://{host}{PATH}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf8"))

def build_jobs():
    """生成全部采集任务"""
    jobs = []
    # 城市榜 (city scope) - schoolName 是必填占位符，不影响城市榜单内容，用城市第一个驾校名
    for dkey, host in HOSTS.items():
        for ccode, cdata in CITIES.items():
            if not cdata:
                continue
            city_name = cdata[0].get("cityName") or ccode
            placeholder_school = cdata[0].get("name", "")
            for ts in TIME_SCOPES:
                jobs.append({
                    "key": f"{dkey}|city|{ccode}|{ts}",
                    "host": host,
                    "biz": {"cityName": city_name, "carType": "car", "cityCode": ccode,
                            "schoolCode": 0, "schoolName": placeholder_school, "areaScope": "city", "timeScope": ts},
                })
    # 驾校榜 (school scope) - 每个城市取前几个驾校
    for dkey, host in HOSTS.items():
        for ccode, cdata in CITIES.items():
            if not cdata:
                continue
            city_name = cdata[0].get("cityName") or ccode
            for ts in TIME_SCOPES:
                # 全国/省份也采, 但学校榜只采代表性驾校(每城前2)
                for school in cdata[:2]:
                    if not isinstance(school, dict) or "code" not in school:
                        continue
                    jobs.append({
                        "key": f"{dkey}|school|{ccode}|{school['code']}|{ts}",
                        "host": host,
                        "biz": {"cityName": city_name, "carType": "car", "cityCode": ccode,
                                "schoolCode": school["code"], "schoolName": school["name"],
                                "areaScope": "school", "timeScope": ts},
                    })
    # 全国榜 (country scope)
    for dkey, host in HOSTS.items():
        for ts in TIME_SCOPES:
            jobs.append({
                "key": f"{dkey}|country|all|{ts}",
                "host": host,
                "biz": {"cityName": "北京", "carType": "car", "cityCode": "110000",
                        "schoolCode": 0, "schoolName": "海淀驾校", "areaScope": "country", "timeScope": ts},
            })
    return jobs

def main():
    jobs = build_jobs()
    total = len(jobs)
    print(f"总任务: {total}")

    # 断点续传
    all_data = {}
    done = 0
    progress_f = OUT / "progress.json"
    if progress_f.exists():
        try:
            pg = json.load(open(progress_f, encoding="utf8"))
            all_data = pg.get("data", {})
            done = len(all_data)
            print(f"续传: 已有 {done} 条")
        except Exception:
            pass
    todo = [j for j in jobs if j["key"] not in all_data]
    print(f"待采: {len(todo)} / {total}")

    fail = 0
    t0 = time.time()
    def work(job):
        for attempt in range(3):
            try:
                d = fetch_rank(job["host"], job["biz"])
                data = d.get("data") if isinstance(d, dict) else None
                if data is None:
                    return job["key"], None, d.get("message", "no data")
                rec = {
                    "domain": job["host"], "areaScope": job["biz"]["areaScope"],
                    "timeScope": job["biz"]["timeScope"],
                    "cityName": job["biz"]["cityName"], "cityCode": job["biz"]["cityCode"],
                    "schoolCode": job["biz"].get("schoolCode"), "schoolName": job["biz"].get("schoolName"),
                    "rankArea": data.get("rankArea"), "dateTime": data.get("dateTime"),
                    "myRank": data.get("myRank"), "rankList": data.get("rankList", []),
                }
                return job["key"], rec, None
            except Exception as e:
                time.sleep(0.5 * (attempt + 1))
        return job["key"], None, f"3x fail"

    batch = []
    with ThreadPoolExecutor(max_workers=CONC) as ex:
        futs = {ex.submit(work, j): j for j in todo}
        for f in futs:
            key, rec, err = f.result()
            if rec:
                all_data[key] = rec
                batch.append(key)
            else:
                fail += 1
                print(f"  FAIL {key}: {err}", flush=True)
            done += 1
            # 每 100 条存一次
            if len(batch) >= 100:
                (OUT / "progress.json").write_text(
                    json.dumps({"done": done, "total": total, "data": all_data},
                               ensure_ascii=False), encoding="utf8")
                print(f"  进度 {done}/{total} 失败{fail} {time.time()-t0:.0f}s", flush=True)
                batch = []

    (OUT / "progress.json").write_text(
        json.dumps({"done": done, "total": total, "data": all_data},
                   ensure_ascii=False), encoding="utf8")
    print(f"\n完成: {done}/{total} 失败{fail} 用时{time.time()-t0:.0f}s")
    # 最终产物: 单独剥离 rankList
    final = {}
    for k, rec in all_data.items():
        rl = rec.pop("rankList")
        final[k] = {**rec, "rankCount": len(rl), "rankList": rl}
    (OUT / "all-rank.json").write_text(
        json.dumps(final, ensure_ascii=False), encoding="utf8")
    print(f"产物: harvested/rank/all-rank.json ({done} 条)")

if __name__ == "__main__":
    main()
