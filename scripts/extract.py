"""按需导出器 v2：基于每库独立数据 data/<car_type>/ 过滤，快速交付。

用法：
  python extract.py --car-type car                       # 全量导出 car 一份（默认）
  python extract.py --car-type car --chapter 三力测试     # car 的三力测试章节
  python extract.py --car-type bus --region 福州          # bus 的福州地方题
  python extract.py --car-type moto --query 高速公路      # moto 含"高速公路"的题
  python extract.py --car-type car --difficulty 1-3       # 难度1-3
  python extract.py --car-type car,bus,moto               # 多库合并（各自独立导出）
  python extract.py --list                                # 列出全部车型+题数

输出：
  <out>/questions.json    命中题（完整解密字段）
  <out>/media/            命中题引用的媒体（自包含）
  <out>/stats.json        统计
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

LIVE_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = LIVE_ROOT / "data"


def list_db() -> None:
    idx = json.loads((DATA_DIR / "index.json").read_text(encoding="utf8"))
    print(f"全库 {idx['count']} 个车型, {idx['total_questions']} 题:")
    for name in sorted(idx["dbs"]):
        st = idx["dbs"][name]
        print(f"  {name:<24} {st['questions']:>7} 题 · 章节{st['chapters']:>4} · 媒体{st['media_copied']:>5}")


def match(q: dict, args) -> bool:
    if args.chapter:
        cname = args.chapter
        chs = [n for n in (q.get("chapter_names") or []) if n]
        if not any(cname in n for n in chs):
            return False
    if args.region:
        region = args.region
        chs = " ".join(n for n in (q.get("chapter_names") or []) if n)
        if region not in chs:
            return False
    if args.query:
        qtext = (q.get("question") or "") + (q.get("explain") or "")
        for kw in args.query.split():
            if kw not in qtext:
                return False
    if args.difficulty:
        lo, _, hi = args.difficulty.partition("-")
        lo, hi = int(lo or 0), int(hi or 5)
        d = q.get("difficulty")
        if d is None or not (lo <= int(d) <= hi):
            return False
    return True


def export_one(car_type: str, args) -> None:
    src_dir = DATA_DIR / car_type
    if not src_dir.exists():
        print(f"[ERR] 车型 {car_type} 不存在 (用 --list 查看)", file=sys.stderr)
        return
    all_q = json.loads((src_dir / "questions.json").read_text(encoding="utf8"))
    hits = [q for q in all_q if match(q, args)]

    out = Path(args.out_dir) / (args.name or car_type)
    media_out = out / "media"
    media_out.mkdir(parents=True, exist_ok=True)

    # 复制命中题的媒体
    media_keys = set()
    copied = 0
    for q in hits:
        mk = q.get("media_key")
        if mk:
            media_keys.add(mk)
    src_media = src_dir / "media"
    for mk in sorted(media_keys):
        ext = ".mp4" if str(mk).startswith("video-") else ".jpg"
        src = src_media / f"{mk}{ext}"
        dst = media_out / f"{mk}{ext}"
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
            copied += 1

    # 输出
    result = {
        "filter": {k: getattr(args, k) for k in
                   ("car_type", "chapter", "region", "query", "difficulty")},
        "count": len(hits),
        "questions": hits,
        "media": {"keys": len(media_keys), "copied": copied},
    }
    (out / "questions.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf8")
    (out / "stats.json").write_text(
        json.dumps({"count": len(hits), "media_copied": copied,
                    "chapters": sorted({n for q in hits for n in (q.get("chapter_names") or []) if n})},
                   ensure_ascii=False, indent=1), encoding="utf8")
    print(f"[{car_type}] {len(hits)}/{len(all_q)} 题 -> {out} (媒体复制 {copied})")


def main() -> int:
    ap = argparse.ArgumentParser(description="驾考宝典按需导出 v2")
    ap.add_argument("--car-type", default="", help="车型(car/bus/...), 多库用逗号")
    ap.add_argument("--chapter", default="", help="章节名过滤")
    ap.add_argument("--region", default="", help="地区名过滤")
    ap.add_argument("--query", default="", help="关键词")
    ap.add_argument("--difficulty", default="", help="难度 1-3")
    ap.add_argument("--out-dir", default=str(LIVE_ROOT / "extracted"))
    ap.add_argument("--name", default="", help="输出子目录名")
    ap.add_argument("--list", action="store_true", help="列出全部车型")
    args = ap.parse_args()

    if args.list:
        list_db()
        return 0
    if not args.car_type:
        print("请指定 --car-type 或用 --list", file=sys.stderr)
        return 1
    for ct in args.car_type.split(","):
        export_one(ct.strip(), args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
