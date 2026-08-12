"""全库完整数据导出：33 个库每题完整画像。

每库输出 live/exports/<db>.full.json：
    {
      "db": "bus",
      "version": "202608061421",
      "car_type": "bus",
      "meta": {...},
      "chapters": [{id,title,parent,...}],
      "exam_rules": [...],
      "questions": [
        {
          "question_id": 800000,
          "question": "...(解密)",
          "answer": 32,
          "options": ["违章行为","违法行为",...],
          "option_type": 1,
          "explain": "...(解密)",
          "concise_explain": "...",
          "keywords": "...",
          "assured_keywords": "...",
          "illiteracy_explain": "...",
          "illiteracy_keywords": "...",
          "explain_keywords": "...",
          "difficulty": 3,
          "wrong_rate": 0.29,
          "media_type": 0,
          "media_key": null,
          "media_local": "media/car/image-3.jpg" | null,
          "chapter_ids": [121,122,...],
          "chapter_names": ["科目一", "交通标志"],
          "areacodes": ["110000",...],
        }, ...
      ],
      "media_imported_from_car": 1242   # 本库引用了 car 但本地没有的媒体数
    }

合并输出 live/exports/all_dbs.json 作为大数据集索引。
媒体跨库补全：题目引用的 media_key 若本库无，则查 car.db（媒体主库）。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

DBS_DIR = Path(__file__).resolve().parent.parent / "dbs"
OUT_DIR = Path(__file__).resolve().parent.parent / "exports"
XOR_KEY = b"_jiakaobaodian.com_"

BLOB_COLUMNS = {
    "question", "explain", "concise_explain", "assured_keywords",
    "illiteracy_explain", "illiteracy_keywords", "keywords", "explain_keywords",
}


def xor_decrypt(data):
    if not data:
        return None
    return bytes(b ^ XOR_KEY[i % len(XOR_KEY)] for i, b in enumerate(data)).decode("utf8", errors="replace")


def export_db(db_path: Path, car_con) -> dict:
    prefix = db_path.stem
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}

    out = {"db": prefix, "version": None, "car_type": prefix,
           "chapters": [], "exam_rules": [], "questions": []}

    # version
    if "t_version" in tables:
        r = con.execute("SELECT * FROM t_version LIMIT 1").fetchone()
        if r:
            d = dict(r)
            out["version"] = str(d.get("version", ""))

    # chapters
    if "t_chapter" in tables:
        for r in con.execute("SELECT * FROM t_chapter"):
            d = dict(r)
            out["chapters"].append({k: v for k, v in d.items()
                                    if not isinstance(v, (bytes, bytearray))})

    # exam rules
    if "t_exam_rule" in tables:
        for r in con.execute("SELECT * FROM t_exam_rule"):
            d = dict(r)
            out["exam_rules"].append({k: v for k, v in d.items()
                                      if not isinstance(v, (bytes, bytearray))})

    # media keys available in this db
    local_media = set()
    if "t_media" in tables:
        for r in con.execute("SELECT media_key FROM t_media"):
            if r[0]:
                local_media.add(r[0])

    # chapter map
    qid_to_chapters = {}
    if "t_chapter_question" in tables:
        rows = con.execute("SELECT * FROM t_chapter_question").fetchall()
        for r in rows:
            d = dict(r)
            cid = d.get("chapter_id")
            qid = d.get("question_id")
            ac = d.get("areacode")
            qid_to_chapters.setdefault(qid, []).append((cid, ac))
    chapter_title = {c.get("_id"): c.get("title", "") for c in out["chapters"]}

    # questions
    tq_cols = [c["name"] for c in con.execute("PRAGMA table_info('t_question')")]
    scalar = [c for c in tq_cols if c not in BLOB_COLUMNS]
    blob_cols = [c for c in tq_cols if c in BLOB_COLUMNS]
    select = ", ".join(scalar + blob_cols)
    missing_media = 0
    for r in con.execute(f"SELECT {select} FROM t_question"):
        d = dict(r)
        q = {"question_id": d.get("question_id")}
        # scalar
        for c in scalar:
            v = d.get(c)
            if isinstance(v, (bytes, bytearray)):
                v = xor_decrypt(v)
            q[c] = v
        # blob 解密
        for c in blob_cols:
            q[c] = xor_decrypt(d.get(c))
        # options 聚合
        q["options"] = [d.get(f"option_{x}") or "" for x in
                        "abcdefgh"]
        # media 补全
        mkey = d.get("media_key")
        if mkey:
            if mkey in local_media:
                q["media_local"] = f"media/{prefix}/{mkey}" + (".mp4" if str(mkey).startswith("video-") else ".jpg")
            else:
                # 尝试从 car 补
                missing_media += 1
                if car_con is not None and mkey in car_keys:
                    q["media_local"] = f"media/car/{mkey}" + (".mp4" if str(mkey).startswith("video-") else ".jpg")
                else:
                    q["media_local"] = None
        else:
            q["media_local"] = None
        # chapters
        chs = qid_to_chapters.get(d.get("question_id"), [])
        q["chapter_ids"] = [c[0] for c in chs]
        q["chapter_names"] = [chapter_title.get(c[0], "") for c in chs]
        q["areacodes"] = [c[1] for c in chs if c[1]]
        out["questions"].append(q)

    out["media_imported_from_car"] = missing_media
    con.close()
    return out


def main() -> int:
    dbs = sorted(DBS_DIR.glob("*.db"))
    # car 媒体主库
    car_con = sqlite3.connect(str(DBS_DIR / "car.db"))
    global car_keys
    car_keys = set(r[0] for r in car_con.execute("SELECT media_key FROM t_media") if r[0])

    all_index = {"count": 0, "dbs": {}, "total_questions": 0}
    print(f"{'db':<24} {'题目':>7} {'章':>5} {'媒体引用':>8} {'缺失补car':>9}")
    print("-" * 65)
    for db in dbs:
        try:
            data = export_db(db, car_con)
        except Exception as e:
            print(f"{db.stem:<24} ERROR: {e}")
            continue
        fname = f"{db.stem}.full.json"
        (OUT_DIR / fname).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf8")
        n = len(data["questions"])
        all_index["dbs"][db.stem] = {
            "file": fname, "version": data["version"], "questions": n,
            "chapters": len(data["chapters"]),
            "missing_media_from_car": data["media_imported_from_car"],
        }
        all_index["total_questions"] += n
        print(f"{db.stem:<24} {n:>7} {len(data['chapters']):>5} "
              f"{sum(1 for q in data['questions'] if q.get('media_key')):>8} "
              f"{data['media_imported_from_car']:>9}")
    all_index["count"] = len(all_index["dbs"])
    (OUT_DIR / "all_dbs.json").write_text(
        json.dumps(all_index, ensure_ascii=False, indent=1), encoding="utf8")
    car_con.close()
    print(f"\n共 {all_index['count']} 个库, {all_index['total_questions']} 题")
    print(f"全库完整数据 -> {OUT_DIR}/<db>.full.json, 索引 -> all_dbs.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
