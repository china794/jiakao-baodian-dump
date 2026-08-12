"""实测 4 个新端点（真实参数已挖到）
  1. rank/list        排行榜 (ke1.jiakaobaodian.com) — 不签名, 只加 _s
  2. vip-practice     VIP练习 (jk-tiku) — 需 dbVersion
  3. app-db/update   题库版本更新 — 需 majorVersion + version JSON
  4. app-db/download 题库整库下载 — 需 carType + majorVersion
"""
import importlib.util, json, sys, time
from pathlib import Path
LIVE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LIVE_ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("h", LIVE_ROOT / "scripts" / "harvest_api.py")
h = importlib.util.module_from_spec(spec); sys.argv = ["x"]; spec.loader.exec_module(h)

CAR_DB = Path(__file__).resolve().parent.parent / "dbs" / "car.db"

def get_tiku_version():
    import sqlite3
    con = sqlite3.connect(str(CAR_DB))
    row = con.execute("SELECT major_version, version FROM t_version").fetchone()
    con.close()
    return row  # (major_version, version)

def probe(name, host, path, biz, need_sign=True):
    print(f"\n=== {name}: {host}{path} ===")
    try:
        if need_sign:
            url = h.sign_url(host, path, biz, want_r=False)
        else:
            # 不签名: 手动拼 query（含 baseParams + biz + _s）
            import urllib.parse
            params = dict(h.BASE_PARAMS) if hasattr(h, 'BASE_PARAMS') else {}
            params.update(biz)
            params['_s'] = h.gen_r(1)
            url = f"https://{host}{path}?" + urllib.parse.urlencode(params)
        d = h.fetch_json(url, timeout=20)
        if d is None:
            print("  fetch failed (None)")
            return
        s = json.dumps(d, ensure_ascii=False)
        print(f"  ok, {len(s)} chars")
        print(f"  keys: {list(d.keys()) if isinstance(d, dict) else type(d).__name__}")
        print(f"  sample: {s[:400]}")
    except Exception as e:
        print(f"  ERR: {str(e)[:200]}")

mv, ver = get_tiku_version()
print(f"t_version: major_version={mv}, version={ver}")

# 1. 排行榜 - 不签名
probe("rank-list (city, week)",
      "ke1.jiakaobaodian.com",
      "/api/open/h5/rank/list.htm",
      {"cityName": "北京", "carType": "car", "cityCode": "110000",
       "schoolCode": 0, "schoolName": "",
       "areaScope": "city", "timeScope": "week"},
      need_sign=False)

# 2. VIP练习 - 签名 + dbVersion
probe("vip-practice (vip-500)",
      "jk-tiku.kakamobi.cn",
      "/api/open/vip/vip-practice.htm",
      {"kemu": "1", "carType": "car", "cityCode": "110000",
       "practiceType": "vip-500", "dbVersion": ver, "sceneCode": "101"})

# 3. 题库版本更新 - 签名 + majorVersion + version JSON
probe("app-db-update",
      "jk-tiku.kakamobi.cn",
      "/api/open/app-db/update-super.htm",
      {"majorVersion": mv, "sceneCode": "101",
       "version": json.dumps([{"carType": "car", "version": str(ver)}]),
       "applicationType": "pc"})

# 4. 题库下载 - 签名 + carType + majorVersion
probe("app-db-download",
      "jk-tiku.kakamobi.cn",
      "/api/open/app-db/download.htm",
      {"carType": "car", "majorVersion": mv, "applicationType": "pc"})
