"""将每库 questions.json 拆为「点哪题加载哪题」结构，替代分片(shards)。

问题：分片按 500题/片 仍是批量加载，用户要求点哪题加载哪题，绝不一次拉全量。

方案：
  data/<car_type>/
    index.json               # 库级轻量索引：章节列表 + 预计算统计 + 典型题卡片（几KB~几百KB）
    chapters/N.json          # 第N章题目元数据数组（id/题型/错误率/难度/媒体）
    q/xx/<question_id>.json  # 单题完整数据（分两段目录防目录过大）

index.json 结构：
  {
    "car_type", "version",
    "count",
    "chapters": [{name, count, file:"chapters/N.json"}],   # 按题数降序
    "stats": {
      "option_type": {judge, single, multi},
      "difficulty": {1..5},
      "wrong_rate": {hard, mid, midlow, easy},
      "media": {image, video, none},
      "avg_wrong_rate",
      "keywords_top": [["词", count], ...]                # assured_keywords TOP15
    },
    "typicals": {                                           # 典型题卡片（预截断题干，无需拉全量）
      "hard":   [{id, chapter, q, wr, ot, media}...6],
      "easy":   [...],
      "multi":  [...],
      "media":  [...],
      "keywords":[...]
    }
  }

章节归属：以每题第一个非空 chapter_names 为主章节，保证 count 求和 == count。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from collections import defaultdict

LIVE_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = LIVE_ROOT / "data"

BADGE_CN = {1: '易', 2: '中', 3: '难', 4: '极难', 5: '地狱'}


def split_lib(car_type: str) -> None:
    lib = DATA_DIR / car_type
    qs_path = lib / "questions.json"
    if not qs_path.exists():
        print(f"[ERR] {car_type}/questions.json 不存在", file=sys.stderr)
        return
    qs = json.loads(qs_path.read_text(encoding="utf8"))
    n = len(qs)
    print(f"[{car_type}] {n} 题")

    # ---------- 1. 按主章节分组（保持原顺序） ----------
    groups = defaultdict(list)   # chapter -> [(orig_idx, q), ...]
    for i, q in enumerate(qs):
        cn = next((x for x in (q.get("chapter_names") or []) if x), "未分类")
        groups[cn].append((i, q))
    order = sorted(groups, key=lambda c: -len(groups[c]))   # 题数降序
    print(f"[{car_type}] 章节 {len(order)} 个")

    # ---------- 2. 写章节元数据文件 ----------
    ch_dir = lib / "chapters"
    ch_dir.mkdir(exist_ok=True)
    chapters_out = []
    for cid, name in enumerate(order):
        items = groups[name]
        meta = []
        for orig_i, q in items:
            mk = q.get("media_key")
            media = 0 if not mk else (2 if q.get("media_type") == 2 else 1)
            meta.append({
                "id": q.get("question_id"),
                "ot": q.get("option_type", 1),
                "wr": q.get("wrong_rate"),
                "diff": q.get("difficulty"),
                "media": media,
            })
        cf = f"chapters/{cid}.json"
        (ch_dir / f"{cid}.json").write_text(
            json.dumps({"name": name, "count": len(items), "questions": meta},
                       ensure_ascii=False), encoding="utf8")
        chapters_out.append({"name": name, "count": len(items), "file": cf})

    # ---------- 3. 写单题文件 q/xx/<qid>.json ----------
    q_dir = lib / "q"
    q_dir.mkdir(exist_ok=True)
    for i, q in enumerate(qs):
        qid = str(q.get("question_id"))
        sub = q_dir / qid[:2]
        sub.mkdir(exist_ok=True)
        (sub / f"{qid}.json").write_text(
            json.dumps(q, ensure_ascii=False), encoding="utf8")
    print(f"[{car_type}] 单题文件写毕")

    # ---------- 4. 预计算统计 ----------
    stats = {
        "option_type": {"judge": 0, "single": 0, "multi": 0},
        "difficulty": {d: 0 for d in range(1, 6)},
        "wrong_rate": {"hard": 0, "mid": 0, "midlow": 0, "easy": 0},
        "media": {"image": 0, "video": 0, "none": 0},
        "avg_wrong_rate": 0,
        "keywords_top": [],
    }
    kw_freq = defaultdict(int)
    wr_sum, wr_cnt = 0, 0
    for q in qs:
        ot = q.get("option_type", 1)
        if ot == 0: stats["option_type"]["judge"] += 1
        elif ot == 2: stats["option_type"]["multi"] += 1
        else: stats["option_type"]["single"] += 1
        d = q.get("difficulty")
        if d is not None and 1 <= int(d) <= 5:
            stats["difficulty"][int(d)] += 1
        wr = q.get("wrong_rate")
        if wr is not None:
            wr_sum += wr; wr_cnt += 1
            if wr >= 0.7: stats["wrong_rate"]["hard"] += 1
            elif wr >= 0.4: stats["wrong_rate"]["mid"] += 1
            elif wr >= 0.2: stats["wrong_rate"]["midlow"] += 1
            else: stats["wrong_rate"]["easy"] += 1
        mk = q.get("media_key")
        if mk:
            if q.get("media_type") == 2: stats["media"]["video"] += 1
            else: stats["media"]["image"] += 1
        else:
            stats["media"]["none"] += 1
        ak = q.get("assured_keywords")
        if ak:
            for w in str(ak).split("|"):
                w = w.strip().replace("，", "").replace(",", "").replace("、", "")
                if len(w) >= 2:
                    kw_freq[w] += 1
    stats["avg_wrong_rate"] = round(wr_sum / wr_cnt * 100, 1) if wr_cnt else 0
    stats["keywords_top"] = sorted(kw_freq.items(), key=lambda kv: -kv[1])[:15]

    # ---------- 5. 典型题卡片（6个类别各6道，卡片预截断题干 + 章节名） ----------
    def ch_name(q):
        return next((x for x in (q.get("chapter_names") or []) if x), "未分类")

    def card(q):
        qid = q.get("question_id")
        mk = q.get("media_key")
        return {
            "id": qid,
            "ch": ch_name(q),
            "q": str(q.get("question") or "")[:90],
            "wr": q.get("wrong_rate"),
            "ot": q.get("option_type", 1),
            "media": 0 if not mk else (2 if q.get("media_type") == 2 else 1),
        }

    wr_rated = [q for q in qs if q.get("wrong_rate") is not None]
    hard = sorted(wr_rated, key=lambda q: -q["wrong_rate"])[:6]
    easy = sorted(wr_rated, key=lambda q: q["wrong_rate"])[:6]
    multi = sorted((q for q in qs if q.get("option_type") == 2),
                   key=lambda q: bin(q.get("answer", 0) & 0xFF).count("1"), reverse=True)[:6]
    media = [q for q in qs if q.get("media_key")][:6]
    keywords = sorted(qs, key=lambda q: len(str(q.get("assured_keywords") or "")) +
                      len(str(q.get("keywords") or "")), reverse=True)[:6]
    typicals = {
        "hard": [card(q) for q in hard],
        "easy": [card(q) for q in easy],
        "multi": [card(q) for q in multi],
        "media": [card(q) for q in media],
        "keywords": [card(q) for q in keywords],
    }

    # ---------- 6. 写 index.json ----------
    index = {
        "car_type": car_type,
        "version": (lib / "stats.json").exists() and
                   json.loads((lib / "stats.json").read_text(encoding="utf8")).get("version"),
        "count": n,
        "chapters": chapters_out,
        "stats": stats,
        "typicals": typicals,
    }
    idx_bytes = len(json.dumps(index, ensure_ascii=False))
    (lib / "index.json").write_text(
        json.dumps(index, ensure_ascii=False), encoding="utf8")
    print(f"[{car_type}] index.json {idx_bytes} 字节 ({idx_bytes/1024:.1f}KB) 完成")


def main() -> int:
    targets = sys.argv[1:] or [p.parent.name for p in DATA_DIR.glob("*/questions.json")]
    for ct in sorted(set(targets)):
        try:
            split_lib(ct)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[{ct}] 失败: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
