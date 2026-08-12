"""驾考宝典数据浏览器 - 前端数据准备
1) dianping: 534MB all-dianping.json -> 按题号拆单文件 frontend/by_qid/<qid>.json
   + frontend/dp_count.json 计数索引
   (前端按需 fetch 单题评论, 不整包加载)
2) rank: 70MB+ progress.json -> frontend/rank_index.json 只留元数据
   (rankList 仍在原文件, 详情按需加载时看 index 里的 key)

用法: python frontend/prep.py
"""
import json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DP_SRC = ROOT / "harvested" / "dianping" / "all-dianping.json"
DP_OUT = Path(__file__).resolve().parent / "by_qid"
DP_CNT = Path(__file__).resolve().parent / "dp_count.json"

RANK_SRC = ROOT / "harvested" / "rank" / "progress.json"
RANK_OUT = Path(__file__).resolve().parent / "rank_index.json"

def prep_dianping():
    DP_OUT.mkdir(parents=True, exist_ok=True)
    # 已有文件数
    existing = set(p.stem for p in DP_OUT.glob("*.json")) if DP_OUT.exists() else set()
    print(f"dianping: 已拆 {len(existing)} 题, 源 {DP_SRC.stat().st_size/1e6:.0f}MB", flush=True)

    count = {}
    done = 0
    with open(DP_SRC, encoding="utf8") as fp:
        # 顶层是 {qid: [...]}. 手写流式解析: 读整文件太大, 用 json 整体读一次也行(约2GB内存)
        # 这里用迭代方式拆, 避免一次驻留
        import io
        # 简化: 整读 (本机内存够), 逐题写文件
        data = json.load(fp)
    total = len(data)
    print(f"dianping: 共 {total} 题, 开始拆分...", flush=True)
    for qid, comments in data.items():
        f = DP_OUT / f"{qid}.json"
        if f.exists():
            count[qid] = len(comments)
            done += 1
            continue
        f.write_text(json.dumps(comments, ensure_ascii=False), encoding="utf8")
        count[qid] = len(comments)
        done += 1
        if done % 500 == 0:
            print(f"  {done}/{total}", flush=True)
    (DP_OUT / "_count.json").write_text(
        json.dumps(count, ensure_ascii=False), encoding="utf8")
    print(f"dianping: 完成 {done} 题, 计数 -> frontend/by_qid/_count.json", flush=True)

def prep_rank():
    if not RANK_SRC.exists():
        print("rank: progress.json 不存在, 跳过"); return
    pg = json.load(open(RANK_SRC, encoding="utf8"))
    data = pg.get("data", {})
    index = {}
    for k, v in data.items():
        index[k] = {
            "domain": v.get("domain"), "areaScope": v.get("areaScope"),
            "timeScope": v.get("timeScope"), "cityName": v.get("cityName"),
            "cityCode": v.get("cityCode"), "schoolCode": v.get("schoolCode"),
            "schoolName": v.get("schoolName"), "rankArea": v.get("rankArea"),
            "dateTime": v.get("dateTime"), "myRank": v.get("myRank"),
            "rankCount": len(v.get("rankList", [])),
        }
    RANK_OUT.write_text(json.dumps({
        "done": pg.get("done"), "total": pg.get("total"), "data": index
    }, ensure_ascii=False), encoding="utf8")
    print(f"rank: 索引 {len(index)} 条 -> frontend/rank_index.json", flush=True)

if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("all", "dianping"):
        prep_dianping()
    if what in ("all", "rank"):
        prep_rank()
