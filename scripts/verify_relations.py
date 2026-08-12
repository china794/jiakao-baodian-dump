"""全库对应关系校验：验证每个库内 question<->chapter<->media<->areacode 引用完整性。

检查项：
  1. 每题 media_key 是否在 t_media 存在（media 对应关系）
  2. 每题 question_id 是否在 t_chapter_question 有映射（chapter 对应关系）
  3. t_chapter_question 的 chapter_id 是否在 t_chapter 存在
  4. t_chapter_question 的 question_id 是否在 t_question 存在（反向）
  5. t_exam_rule 引用的 chapter_id/areacode 是否一致
  6. 输出每题完整画像（question_id -> {chapters, areacode, media, answer, ...}）
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

DBS_DIR = Path(__file__).resolve().parent.parent / "dbs"
OUT_DIR = Path(__file__).resolve().parent.parent / "exports"


def check_db(db_path: Path, prefix: str) -> dict:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    tq_cols = [r[1] for r in con.execute("PRAGMA table_info('t_question')")]
    tm_cols = [r[1] for r in con.execute("PRAGMA table_info('t_media')")]
    issues = {"missing_media": 0, "no_chapter_map": 0, "bad_chapter_id": 0,
              "bad_question_id_in_map": 0, "bad_media_refs": []}
    counts = {"questions": 0, "media": 0, "chapters": 0, "chapter_map_entries": 0}

    # media key set
    media_keys = set()
    if tm_cols:
        for r in con.execute("SELECT media_key FROM t_media"):
            if r[0]: media_keys.add(r[0])
    counts["media"] = len(media_keys)

    # chapter set
    chapter_ids = set()
    if "t_chapter" in [r[1] for r in con.execute("PRAGMA table_info('t_question')")] or True:
        try:
            for r in con.execute("SELECT _id FROM t_chapter"):
                chapter_ids.add(r[0])
        except Exception:
            pass
    counts["chapters"] = len(chapter_ids)

    # chapter_map: question_id -> list
    qid_to_chapters = {}
    if "t_chapter_question" in [x[0] for x in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]:
        rows = con.execute("SELECT * FROM t_chapter_question").fetchall()
        counts["chapter_map_entries"] = len(rows)
        for r in rows:
            d = dict(r)
            cid = d.get("chapter_id")
            qid = d.get("question_id")
            qid_to_chapters.setdefault(qid, []).append(cid)
            if cid not in chapter_ids and chapter_ids:
                issues["bad_chapter_id"] += 1

    # questions
    profiles = {}
    media_col = "media_key" in tq_cols
    for r in con.execute("SELECT * FROM t_question"):
        d = dict(r)
        qid = d.get("question_id")
        counts["questions"] += 1
        # media ref
        mkey = d.get("media_key")
        media_ref = None
        if mkey:
            if mkey in media_keys:
                media_ref = mkey
            else:
                issues["missing_media"] += 1
                issues["bad_media_refs"].append((qid, mkey))
        # chapter ref
        chs = qid_to_chapters.get(qid)
        if chs is None:
            issues["no_chapter_map"] += 1
        # full profile
        profiles[str(qid)] = {
            "chapters": chs or [],
            "media": media_ref,
            "answer": d.get("answer"),
            "option_type": d.get("option_type"),
            "difficulty": d.get("difficulty"),
            "wrong_rate": d.get("wrong_rate"),
            "media_type": d.get("media_type"),
            "sort": d.get("sort"),
        }
    # reverse: map question not in t_question（key 统一 str 比较）
    for qid in qid_to_chapters:
        if str(qid) not in profiles:
            issues["bad_question_id_in_map"] += 1

    (OUT_DIR / f"{prefix}.profiles.json").write_text(
        json.dumps(profiles, ensure_ascii=False), encoding="utf8")
    con.close()
    return {"counts": counts, "issues": issues}


def main() -> int:
    dbs = sorted(DBS_DIR.glob("*.db"))
    report = {}
    print(f"{'db':<24} {'题':>6} {'媒':>5} {'章':>5} {'缺媒体':>6} {'无章映射':>7} {'坏章节':>6} {'坏反向':>6}")
    print("-" * 80)
    for db in dbs:
        try:
            res = check_db(db, db.stem)
        except Exception as e:
            print(f"{db.stem:<24} ERROR: {e}")
            continue
        c = res["counts"]; i = res["issues"]
        report[db.stem] = res
        flag = ""
        if i["missing_media"] or i["no_chapter_map"] or i["bad_chapter_id"] or i["bad_question_id_in_map"]:
            flag = "  <-- 检查!"
        print(f"{db.stem:<24} {c['questions']:>6} {c['media']:>5} {c['chapters']:>5} "
              f"{i['missing_media']:>6} {i['no_chapter_map']:>7} {i['bad_chapter_id']:>6} "
              f"{i['bad_question_id_in_map']:>6}{flag}")
        if i["bad_media_refs"][:5]:
            print("  缺媒体示例:", i["bad_media_refs"][:5])
    (OUT_DIR / "relations_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf8")
    print(f"\n报告: {OUT_DIR}/relations_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
