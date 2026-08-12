"""探针：验证 renderer.js 挖出的新端点
  1. rank/list       排行榜 (ke1.jiakaobaodian.com)
  2. vip-practice    VIP练习 (jk-tiku)
  3. app-db/update   题库版本更新检查
  4. app-db/download 题库整库下载
"""
import importlib.util, json, sys, time
from pathlib import Path
LIVE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LIVE_ROOT/"scripts"))
spec = importlib.util.spec_from_file_location("h", LIVE_ROOT/"scripts"/"harvest_api.py")
h = importlib.util.module_from_spec(spec); sys.argv=["x"]; spec.loader.exec_module(h)

def probe(name, host, path, biz, post=False):
    print(f"\n=== {name}: {host}{path} ===")
    try:
        if post:
            url = h.sign_url(host, path, biz, want_r=True)
            d = h.fetch_json(url, timeout=20)
        else:
            url = h.sign_url(host, path, biz, want_r=True)
            d = h.fetch_json(url, timeout=20)
        if d is None:
            print("  fetch failed (None)")
        else:
            s = json.dumps(d, ensure_ascii=False)
            print(f"  ok, {len(s)} chars")
            print(f"  keys: {list(d.keys()) if isinstance(d,dict) else type(d).__name__}")
            print(f"  sample: {s[:300]}")
    except Exception as e:
        print(f"  ERR: {str(e)[:150]}")

# 1. 排行榜 - 用真实城市参数
probe("rank-list",
      "ke1.jiakaobaodian.com",
      "/api/open/h5/rank/list.htm",
      {"cityName":"北京市","cityCode":"110000","carType":"c1","schoolCode":"","schoolName":"",
       "areaScope":"city","timeScope":"week"},
      post=False)

# 2. VIP练习 - 透传参数
probe("vip-practice",
      "jk-tiku.kakamobi.cn",
      "/api/open/vip/vip-practice.htm",
      {"carType":"car","kemu":"1"},
      post=False)

# 3. 题库版本更新
probe("app-db-update",
      "jk-tiku.kakamobi.cn",
      "/api/open/app-db/update-super.htm",
      {"version": json.dumps({"car":{"version":"202608061421"}}), "applicationType":"pc"},
      post=False)

# 4. 题库下载
probe("app-db-download",
      "jk-tiku.kakamobi.cn",
      "/api/open/app-db/download.htm",
      {"applicationType":"pc"},
      post=False)
