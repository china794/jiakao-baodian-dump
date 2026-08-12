"""全业务域 API 采集器：把驾考宝典客户端暴露的 API 端点能拉的全拉下来。

背景：题库已全（33库 225688 题），但客户端还暴露了大量业务 API 未拉取：
  路线视频、视频解析、交通图标、课件、考试项目、汽车品牌、三力测试、
  通过率、FAQ、配置、资源、会员、VIP、驾校城市等。

方法：
  1. 从 renderer.js 提取端点（含域名）
  2. 对每个端点用合理参数签名探测
  3. 能拉到的数据存 harvested/<domain>/<name>.json，归类存档

依赖：sign_runner 常驻签名服务（D:\\Users\\lenovo\\AppData\\Local\\驾考宝典\\sign_runner\\run_server.js）
  机制：TCP 127.0.0.1:8887 逐行请求签名。服务启动后不动 package.json / 不弹客户端。
  启动：临时把 main 指向 run_server.js → exe → 8887 监听（之后 main 固定 run_server.js）。

用法：
  python scripts/harvest_api.py                    # 全量探测
  python scripts/harvest_api.py --list             # 列出端点不清点
  python scripts/harvest_api.py --only exam-project # 只跑某组
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

LIVE_ROOT = Path(__file__).resolve().parent.parent
HARVEST_DIR = LIVE_ROOT / "harvested"
RENDERER = Path(r"D:\Users\lenovo\AppData\Local\驾考宝典\dist\renderer.js")

# 复用 sync_all 的 HTTP 工具，但签名要自己写（支持多域名 host）
spec = importlib.util.spec_from_file_location("sync_all", LIVE_ROOT / "scripts" / "sync_all.py")
sync = importlib.util.module_from_spec(spec)
sys.argv = ["x"]
spec.loader.exec_module(sync)

# 签名机参数文件（直接复用 sync_all 的路径常量）
PARAMS_FILE = sync.PARAMS_FILE
RESULT_FILE = sync.RESULT_FILE
EXE = sync.EXE
JIAKAO_ROOT = sync.JIAKAO_ROOT
# 签名机全局锁：per-request 机制共享 params/result 文件，必须串行
SIGN_LOCK = threading.Lock()

# ============ _r 生成器（与 renderer.js 模块2394 的 Gj 函数同款逻辑）============
def gen_r(e: int) -> str:
    """生成官方 _r 参数：`str(e)+随机数字串+3位校验和`。
    官方 JS: n=abs(parseInt(time*random*1e4)) → 数字和t+len(n) → 3位补零。"""
    import random as _rnd
    n = str(abs(int((time.time() * 1e3) * _rnd.random() * 1e4)))
    t = 0
    for ch in n:
        t += int(ch)
    t += len(n)
    t = str(t).zfill(3)
    return f"{e}{n}{t}"

def sign_host(host: str, path: str, biz: dict | None = None, biz_raw: str | None = None,
              extra: dict | None = None) -> dict:
    """对指定 host + path 签名。per-request 签名机：
    写 params.json → 确保 main 指向 run.js → 启动 exe（不弹GUI，跑签名）→ 等 result.json → 杀进程。
    全程不改 main（保持 run.js），采集完由外部恢复 main 为用户入口。
    extra: 签名后追加到 URL 的参数（如 _r），不参与签名。"""
    with SIGN_LOCK:
        params = {"path": path, "host": host}
        if biz is not None:
            params["biz"] = biz
        if biz_raw is not None:
            params["bizRaw"] = biz_raw
        if extra is not None:
            params["extra"] = extra
        PARAMS_FILE.write_text(json.dumps(params, ensure_ascii=False), encoding="utf8")
        RESULT_FILE.unlink(missing_ok=True)
        proc = subprocess.Popen([str(EXE)], cwd=str(JIAKAO_ROOT),
                                creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.time() + 15
        while time.time() < deadline:
            if RESULT_FILE.exists():
                break
            time.sleep(0.3)
        try:
            proc.terminate()
        except Exception:
            pass
        time.sleep(0.5)
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass
        if not RESULT_FILE.exists():
            tail = (JIAKAO_ROOT / "sign_runner_out.txt").read_text(encoding="utf8", errors="replace")[-500:] \
                if (JIAKAO_ROOT / "sign_runner_out.txt").exists() else ""
            raise RuntimeError(f"签名失败（无 result.json）\n{tail}")
        result = json.loads(RESULT_FILE.read_text(encoding="utf8"))
        if not result.get("ok"):
            raise RuntimeError(f"签名失败: {result.get('error')}")
        return result

# 已有的 33 个车型（题库已拉全，不用再探测车型）
KNOWN_CAR_TYPES = set(
    """baozha baozha_yayun baozha_zhuangxie bus car chache chuzu fixed_bvr fixed_coach
    fixed_wvr helicopter_bvr helicopter_coach helicopter_wvr huoyun jiaolian
    jiaolian_zaijiaoyu judu judu_yayun judu_zhuangxie keyun light_trailer moto
    multi_bvr multi_coach multi_wvr truck vtol_bvr vtol_coach vtol_wvr wangyue
    weixian weixian_yayun weixian_zhuangxie""".split())

# ============ 端点清单：每个端点的探测参数（真实参数从 renderer.js 调用点挖出）============
# group: 业务分组名（用于目录归档和 --only 过滤）
# host: 完整域名
# path: API 路径
# args: 探测用业务参数（renderer.js 真实调用参数；None=不带参数直接试）
# desc: 描述
ENDPOINTS = [
    # ---- 考试项目 / 车型品牌（panda）----
    {"group": "exam-project", "host": "panda.kakamobi.cn",
     "path": "/api/open/exam-project/list.htm",
     "args": {"kemu": "1", "tiku": "car", "cursor": 0, "pageSize": 100, "encodeVersion": 1},
     "desc": "考试项目列表（全部车型/科目，分页）"},
    {"group": "exam-project", "host": "panda.kakamobi.cn",
     "path": "/api/open/exam-project/get-car-brand-list.htm",
     "args": {"kemu": "1", "tiku": "car"},
     "desc": "汽车品牌列表"},

    # ---- 路线视频（panda）----
    {"group": "route-video", "host": "panda.kakamobi.cn",
     "path": "/api/open/route-video/area-list.htm",
     "args": {"cityCode": "110000"},
     "desc": "路线视频地区列表"},
    {"group": "route-video", "host": "panda.kakamobi.cn",
     "path": "/api/open/route-video/place-list.htm",
     "args": {"cityCode": "110000", "areaCode": "110100"},
     "desc": "路线视频考场列表"},
    {"group": "route-video", "host": "panda.kakamobi.cn",
     "path": "/api/open/route-video/show-entrance.htm",
     "args": {"cityCode": "110000"},
     "desc": "路线视频入口配置"},
    {"group": "route-video", "host": "panda.kakamobi.cn",
     "path": "/api/open/route-video/list-data.htm",
     "args": {"cityCode": "110000", "placeId": "1", "version": ""},
     "desc": "路线视频数据"},
    {"group": "route-video", "host": "panda.kakamobi.cn",
     "path": "/api/open/route-video/detail.htm",
     "args": {"id": "1", "placeId": "1", "version": ""},
     "desc": "路线视频详情"},

    # ---- 交通图标（panda）----
    {"group": "traffic-icon", "host": "panda.kakamobi.cn",
     "path": "/api/open/traffic-icon/group-list.htm",
     "args": {"carType": "car"},
     "desc": "交通图标分组"},
    {"group": "traffic-icon", "host": "panda.kakamobi.cn",
     "path": "/api/open/traffic-icon/icon-list.htm",
     "args": {"groupId": "1", "carType": "car"},
     "desc": "交通图标列表"},

    # ---- 课件（panda）----
    {"group": "kejian", "host": "panda.kakamobi.cn",
     "path": "/api/open/kejian/project-list.htm",
     "args": {"kemu": "1"},
     "desc": "课件项目列表"},
    {"group": "kejian", "host": "panda.kakamobi.cn",
     "path": "/api/open/kejian/lecture-list.htm",
     "args": {"projectId": "1", "kemu": "1"},
     "desc": "课件讲义列表"},

    # ---- 通过率 / 配置 / FAQ / 资源（jiakao-misc）----
    {"group": "misc", "host": "jiakao-misc.kakamobi.cn",
     "path": "/api/open/pass-rate/get-pass-rate.htm",
     "args": {},
     "desc": "通过率"},
    {"group": "misc", "host": "jiakao-misc.kakamobi.cn",
     "path": "/api/open/resource-config/get-resource-list.htm",
     "args": {},
     "desc": "资源列表"},
    {"group": "misc", "host": "jiakao-misc.kakamobi.cn",
     "path": "/api/open/light-emulator/banner.htm",
     "args": {},
     "desc": "灯光模拟banner"},
    {"group": "misc", "host": "jiakao-misc.kakamobi.cn",
     "path": "/api/open/operation-config/get-pc-live-operation.htm",
     "args": {},
     "desc": "PC直播运营配置"},
    {"group": "misc", "host": "jiakao-misc.kakamobi.cn",
     "path": "/api/open/faq/list.htm",
     "args": {"kemu": 3, "status": 2, "routeId": "1", "placeId": "1"},
     "desc": "路线视频FAQ"},
    {"group": "misc", "host": "jiakao-misc.kakamobi.cn",
     "path": "/api/open/config/get-config.htm",
     "args": {"key": "kemu1"},
     "desc": "全局配置"},

    # ---- 三力测试 / 重学题库 / 视频解析（jk-tiku）----
    {"group": "tiku-ext", "host": "jk-tiku.kakamobi.cn",
     "path": "/api/web/exam/san-li-exam-question-list.htm",
     "args": {},
     "desc": "三力测试题库（题ID列表）"},
    {"group": "tiku-ext", "host": "jk-tiku.kakamobi.cn",
     "path": "/api/open/relearn/question-list.htm",
     "args": {"carType": "car", "seqnum": 1, "sceneCode": "102", "course": "kemu1",
              "patternCode": "101", "kemuStyle": 1, "bizCode": "8.13.0"},
     "desc": "重学题库（seqnum=1/2/3 三种场景）"},
    {"group": "tiku-ext", "host": "jk-tiku.kakamobi.cn",
     "path": "/api/open/video-explain/get-video-list.htm",
     "args": {"carType": "car", "kemu": "1", "sceneCode": "kemu1"},
     "desc": "视频解析列表"},
    {"group": "tiku-ext", "host": "jk-tiku.kakamobi.cn",
     "path": "/api/open/vip/question-explain.htm",
     "args": {"carType": "car", "kemu": "1", "sceneCode": "kemu1",
              "questionList": ["800000"]},
     "desc": "VIP题目解析"},
    {"group": "tiku-ext", "host": "jk-tiku.kakamobi.cn",
     "path": "/api/open/feedback/banner.htm",
     "args": {"_r": "1"},
     "desc": "反馈banner（POST，需表单）"},

    # ---- 会员 / VIP / 权限（sirius / pony / squirrel / short-video）----
    {"group": "member", "host": "sirius.kakamobi.cn",
     "path": "/api/open/vip-level-info/get.htm",
     "args": {"carType": "car", "sceneCode": "kemu1"},
     "desc": "VIP等级信息"},
    {"group": "member", "host": "pony.kakamobi.cn",
     "path": "/api/open/user-member-identity/get-user-identity.htm",
     "args": {"carType": "car", "sceneCode": "kemu1"},
     "desc": "用户会员身份"},
    {"group": "member", "host": "pony.kakamobi.cn",
     "path": "/api/open/permission/has-permissions.htm",
     "args": {"permissions": "vip", "needValidate": True},
     "desc": "权限列表"},
    {"group": "member", "host": "pony.kakamobi.cn",
     "path": "/api/open/vip-badge/vip-badges.htm",
     "args": {"carType": "car", "sceneCode": "kemu1"},
     "desc": "VIP徽章"},
    {"group": "member", "host": "squirrel.kakamobi.cn",
     "path": "/api/open/order/get-order-status.htm",
     "args": {"orderNos": "1"},
     "desc": "订单状态"},
    {"group": "member", "host": "short-video.kakamobi.cn",
     "path": "/api/open/video/question-origin-video-detail.htm",
     "args": {"idList": "800000"},
     "desc": "题目原题视频"},

    # ---- 驾校（jiaxiao）----
    {"group": "jiaxiao", "host": "jiaxiao.kakamobi.cn",
     "path": "/api/web/v3/jiaxiao/list-city.htm",
     "args": {"cityCode": "110000"},
     "desc": "驾校城市列表"},
]

# ============ 工具 ============
def sign_url(host: str, path: str, biz: dict | None, want_r: bool = True) -> str | None:
    """对指定域名+路径签名，返回完整可访问 URL；失败返回 None。
    want_r=True 时把官方同款 _r 参数加进 biz（参与签名，与官方一致）。"""
    try:
        if want_r:
            biz = dict(biz or {})
            biz.setdefault("_r", gen_r(1))
        result = sign_host(host, path, biz=biz)
        return result.get("fullUrl")
    except Exception as e:
        print(f"  签名失败: {str(e)[:120]}")
        return None

def fetch_json(url: str, timeout: int = 20) -> dict | None:
    try:
        data = sync.get_json(url, timeout=timeout)
        return data
    except Exception as e:
        print(f"  请求失败: {str(e)[:120]}")
        return None

def harvest_one(ep: dict, only_group: str | None) -> None:
    group = ep["group"]
    if only_group and group != only_group:
        return
    host, path = ep["host"], ep["path"]
    name = path.rstrip(".htm").split("/")[-1]
    out_dir = HARVEST_DIR / group
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{name}.json"

    print(f"[{group}] {path}  ({ep['desc']})")
    url = sign_url(host, path, ep["args"])
    if not url:
        out_file.write_text(json.dumps({"error": "sign failed"}, ensure_ascii=False), encoding="utf8")
        return
    data = fetch_json(url)
    if data is None:
        out_file.write_text(json.dumps({"error": "fetch failed"}, ensure_ascii=False), encoding="utf8")
        return
    out_file.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf8")
    s = json.dumps(data, ensure_ascii=False)
    print(f"  -> {out_file.relative_to(LIVE_ROOT)}  ({len(s)}字节)")
    print(f"     样例: {s[:200]}")
    print()

def main() -> int:
    args = sys.argv[1:]
    if "--list" in args:
        for ep in ENDPOINTS:
            print(f"[{ep['group']:<12}] {ep['host']}{ep['path']}  {ep['desc']}")
        return 0
    only = None
    if "--only" in args:
        i = args.index("--only")
        only = args[i + 1]
    HARVEST_DIR.mkdir(exist_ok=True)
    for ep in ENDPOINTS:
        harvest_one(ep, only)
    print("采集完成。产物在 harvested/ 目录。")
    return 0

if __name__ == "__main__":
    sys.exit(main())
