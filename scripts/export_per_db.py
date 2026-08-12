"""每库独立完整数据集导出器。

目标：每个车型库一个完全独立的目录，写前端/数据库直接取用，不依赖其他库。
  data/
    car/          questions.json(6406题,解密完整) + media/(自包含) + chapters.json + exam_rules.json + stats.json
    bus/          同样自包含（媒体从 car 主库补全，bus 目录内可见）
    ...
    index.json    全库索引

每库独立完整性保证：
  1. questions.json = 该库全部题（解密），一个不少
  2. media/ = 该库题目引用的全部媒体（本地有 + 从 car 补全），每库自包含
  3. chapters/exam_rules/stats 齐全
  4. 无跨库依赖：bus 用到的图即使物理上源自 car，也在 bus/media/ 里有一份
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

LIVE_ROOT = Path(__file__).resolve().parent.parent
DBS_DIR = LIVE_ROOT / "dbs"
MEDIA_DIR = LIVE_ROOT / "media"
MEDIA_POOL = MEDIA_DIR / "pool"
DATA_DIR = LIVE_ROOT / "data"
XOR_KEY = b"_jiakaobaodian.com_"

BLOB_COLUMNS = {"question", "explain", "concise_explain", "assured_keywords",
                "illiteracy_explain", "illiteracy_keywords", "keywords",
                "explain_keywords"}


def xor_decrypt_bytes(data: bytes) -> bytes:
    if not data:
        return data
    return bytes(b ^ XOR_KEY[i % len(XOR_KEY)] for i, b in enumerate(data))


def xor_decrypt(data) -> str | None:
    if not data:
        return None
    return xor_decrypt_bytes(bytes(data)).decode("utf8", errors="replace")


def load_full_db(db_path: Path, car_type: str) -> dict:
    """读一个库全部数据（解密），返回统一结构（同 <db>.full.json 但可复用）。"""
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    out = {"car_type": car_type, "version": None, "chapters": [],
           "exam_rules": [], "questions": []}

    if "t_version" in tables:
        r = con.execute("SELECT * FROM t_version LIMIT 1").fetchone()
        if r:
            d = dict(r)
            out["version"] = str(d.get("version", ""))

    if "t_chapter" in tables:
        for r in con.execute("SELECT * FROM t_chapter"):
            d = {k: (v if not isinstance(v, (bytes, bytearray)) else v.hex())
                 for k, v in dict(r).items()}
            out["chapters"].append(d)
    if "t_exam_rule" in tables:
        for r in con.execute("SELECT * FROM t_exam_rule"):
            out["exam_rules"].append(
                {k: v for k, v in dict(r).items()
                 if not isinstance(v, (bytes, bytearray))})

    # chapter map
    chapter_title = {c.get("_id"): c.get("title", "") for c in out["chapters"]}
    qid_chapters = {}
    if "t_chapter_question" in tables:
        for r in con.execute("SELECT * FROM t_chapter_question"):
            d = dict(r)
            qid_chapters.setdefault(d.get("question_id"), []).append(
                (d.get("chapter_id"), d.get("areacode")))

    # local media
    local_media = set()
    if "t_media" in tables:
        for r in con.execute("SELECT media_key FROM t_media"):
            if r[0]:
                local_media.add(r[0])

    # questions
    tq_cols = [c["name"] for c in con.execute("PRAGMA table_info('t_question')")]
    scalar = [c for c in tq_cols if c not in BLOB_COLUMNS]
    blob_cols = [c for c in tq_cols if c in BLOB_COLUMNS]
    for r in con.execute(f"SELECT {', '.join(scalar + blob_cols)} FROM t_question"):
        d = dict(r)
        qid = d.get("question_id")
        q = {"uid": f"{car_type}:{qid}", "car_type": car_type,
             "question_id": qid}
        for c in scalar:
            v = d.get(c)
            if isinstance(v, (bytes, bytearray)):
                v = xor_decrypt(v)
            q[c] = v
        for c in blob_cols:
            q[c] = xor_decrypt(d.get(c))
        q["options"] = [d.get(f"option_{x}") or "" for x in "abcdefgh"]
        mkey = d.get("media_key")
        q["media_key"] = mkey
        chs = qid_chapters.get(qid, [])
        q["chapter_ids"] = [c[0] for c in chs]
        q["chapter_names"] = [chapter_title.get(c[0], "") for c in chs]
        q["areacodes"] = [c[1] for c in chs if c[1]]
        out["questions"].append(q)
    con.close()
    return out


def build_media_map() -> dict:
    """全库媒体映射：db/media_key -> pool 相对路径。"""
    mmap = {}
    for f in (MEDIA_DIR / "media_map.json").read_text(encoding="utf8"):
        pass
    return json.loads((MEDIA_DIR / "media_map.json").read_text(encoding="utf8"))


def export_one(db_path: Path, out_dir: Path, mmap: dict) -> dict:
    """导出一个库的独立数据集。返回统计。"""
    ct = db_path.stem
    data = load_full_db(db_path, ct)
    db_out = out_dir / ct
    media_out = db_out / "media"
    media_out.mkdir(parents=True, exist_ok=True)

    # 1. 收集该库题目引用的 media_key（本地+跨库car）
    media_keys = set()
    for q in data["questions"]:
        mk = q.get("media_key")
        if mk:
            media_keys.add(mk)

    # 2. 复制媒体：本库映射 + car 补全
    #    media_map key 形如 "car/image-3" -> "pool/xxx.jpg"
    copied = 0
    unresolved = []
    media_local_map = {}
    for mk in sorted(media_keys):
        # 先本库
        ref_local = f"{ct}/{mk}"
        pool = mmap.get(ref_local)
        if pool is None:
            # 跨库补 car
            ref_car = f"car/{mk}"
            pool = mmap.get(ref_car)
        if pool is None:
            unresolved.append(mk)
            continue
        src = MEDIA_DIR / pool
        ext = ".mp4" if mk.startswith("video-") else ".jpg"
        dst = media_out / f"{mk}{ext}"
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
            copied += 1
        media_local_map[mk] = f"media/{mk}{ext}"

    # 3. 写文件
    (db_out / "questions.json").write_text(
        json.dumps(data["questions"], ensure_ascii=False), encoding="utf8")
    (db_out / "chapters.json").write_text(
        json.dumps(data["chapters"], ensure_ascii=False, indent=1), encoding="utf8")
    (db_out / "exam_rules.json").write_text(
        json.dumps(data["exam_rules"], ensure_ascii=False, indent=1), encoding="utf8")
    stats = {
        "car_type": ct,
        "version": data["version"],
        "questions": len(data["questions"]),
        "chapters": len(data["chapters"]),
        "exam_rules": len(data["exam_rules"]),
        "media_keys": len(media_keys),
        "media_copied": copied,
        "media_unresolved": len(unresolved),
        "unresolved_keys": unresolved[:10],
        "media_local_map": media_local_map,
    }
    (db_out / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf8")
    return stats


def main() -> int:
    dbs = sorted(DBS_DIR.glob("*.db"))
    mmap = build_media_map()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    index = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
             "count": 0, "total_questions": 0, "dbs": {}}
    print(f"{'库':<24}{'题':>7}{'章节':>6}{'媒体引用':>8}{'复制':>6}{'未解析':>7}")
    print("-" * 65)
    for db in dbs:
        try:
            st = export_one(db, DATA_DIR, mmap)
        except Exception as e:
            print(f"{db.stem:<24} ERROR: {e}")
            continue
        index["count"] += 1
        index["total_questions"] += st["questions"]
        index["dbs"][db.stem] = st
        flag = "  <-- 未解析!" if st["media_unresolved"] else ""
        print(f"{db.stem:<24}{st['questions']:>7}{st['chapters']:>6}"
              f"{st['media_keys']:>8}{st['media_copied']:>6}{st['media_unresolved']:>7}{flag}")
    (DATA_DIR / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf8")
    print(f"\n共 {index['count']} 库, {index['total_questions']} 题")
    print(f"每库独立数据 -> {DATA_DIR}/<car_type>/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
