"""全库挖掘：对 live/dbs/ 下每个 .db 导出完整元数据。

输出（写到 live/exports/）：
  <db>.tables.json       所有表名+列结构
  <db>.chapters.json     t_chapter 标签/章节
  <db>.chapter_map.json  t_chapter_question 对应关系 (question_id -> [chapters])
  <db>.media_list.json   t_media 媒体清单
  <db>.exam_rules.json   t_exam_rule 考试规则
  <db>.questions_meta.json  题目基础字段（不含 blob 正文）
  summary.json           汇总所有库
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

DBS_DIR = Path(__file__).resolve().parent.parent / "dbs"
OUT_DIR = Path(__file__).resolve().parent.parent / "exports"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 加密 blob 列（XOR key _jiakaobaodian.com_）
XOR_KEY = b"_jiakaobaodian.com_"
BLOB_COLUMNS = {
    "question", "explain", "concise_explain", "assured_keywords",
    "illiteracy_explain", "illiteracy_keywords", "keywords",
    "explain_keywords", "media_content",
}


def jstr(v):
    """bytes -> '<bytes len=N>'，其余原样。"""
    if isinstance(v, (bytes, bytearray)):
        return f"<bytes len={len(v)}>"
    return v


def xor_decrypt(data: bytes) -> bytes:
    if not data:
        return data
    return bytes(b ^ XOR_KEY[i % len(XOR_KEY)] for i, b in enumerate(data))


def table_schema(con: sqlite3.Connection) -> dict:
    out = {}
    rows = con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    for name, sql in rows:
        cols = []
        if sql:
            for row in con.execute(f"PRAGMA table_info('{name}')"):
                cols.append({
                    "cid": row[0], "name": row[1], "type": row[2],
                    "notnull": row[3], "dflt": row[4], "pk": row[5],
                })
        out[name] = {"sql": sql, "cols": cols}
    return out


def mine_db(db_path: Path, prefix: str) -> dict:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    summary = {"tables": {}, "question_count": 0, "chapter_count": 0,
               "media_count": 0, "media_types": {}, "exam_rules": 0}

    # 1. 表结构
    schemas = table_schema(con)
    (OUT_DIR / f"{prefix}.tables.json").write_text(
        json.dumps(schemas, ensure_ascii=False, indent=1), encoding="utf8")
    summary["tables"] = {k: {"cols": [c["name"] for c in v["cols"]],
                              "col_types": {c["name"]: c["type"] for c in v["cols"]}}
                         for k, v in schemas.items()}

    # 2. t_question 基础元数据（不取 blob 正文，只取标量字段）
    qcols = [c["name"] for c in schemas.get("t_question", {}).get("cols", [])]
    if qcols:
        scalar_cols = [c for c in qcols if c not in BLOB_COLUMNS]
        rows = con.execute(
            f"SELECT {', '.join(scalar_cols)} FROM t_question").fetchall()
        qmeta = [dict(r) for r in rows]
        (OUT_DIR / f"{prefix}.questions_meta.json").write_text(
            json.dumps(qmeta, ensure_ascii=False), encoding="utf8")
        summary["question_count"] = len(qmeta)

    # 3. t_chapter 标签/章节
    if "t_chapter" in schemas:
        rows = con.execute("SELECT * FROM t_chapter").fetchall()
        chapters = [{k: jstr(v) for k, v in dict(r).items()} for r in rows]
        (OUT_DIR / f"{prefix}.chapters.json").write_text(
            json.dumps(chapters, ensure_ascii=False, indent=1), encoding="utf8")
        summary["chapter_count"] = len(chapters)

    # 4. t_chapter_question 对应关系
    if "t_chapter_question" in schemas:
        rows = con.execute("SELECT * FROM t_chapter_question").fetchall()
        cmap = {}
        for r in rows:
            d = {k: jstr(v) for k, v in dict(r).items()}
            qid = d.get("question_id")
            cmap.setdefault(str(qid), []).append(d)
        (OUT_DIR / f"{prefix}.chapter_map.json").write_text(
            json.dumps(cmap, ensure_ascii=False), encoding="utf8")

    # 5. t_media 媒体清单（media_type 由 media_key 前缀推导：image-* 图片 / video-* 视频）
    if "t_media" in schemas:
        rows = con.execute("SELECT * FROM t_media").fetchall()
        mlist = []
        for r in rows:
            d = dict(r)
            if "media_content" in d and d.get("media_content"):
                d["media_content_size"] = len(d["media_content"])
                d["media_content_head"] = bytes(d["media_content"][:8]).hex()
                d["media_content"] = "<blob>"
            key = str(d.get("media_key") or "")
            d["media_type"] = 2 if key.startswith("video-") else 1 if key.startswith("image-") else 0
            mlist.append(d)
        (OUT_DIR / f"{prefix}.media_list.json").write_text(
            json.dumps(mlist, ensure_ascii=False, indent=1), encoding="utf8")
        summary["media_count"] = len(mlist)
        for m in mlist:
            mt = m["media_type"]
            summary["media_types"][str(mt)] = summary["media_types"].get(str(mt), 0) + 1

    # 6. t_exam_rule
    if "t_exam_rule" in schemas:
        rows = con.execute("SELECT * FROM t_exam_rule").fetchall()
        (OUT_DIR / f"{prefix}.exam_rules.json").write_text(
            json.dumps([{k: jstr(v) for k, v in dict(r).items()} for r in rows],
                       ensure_ascii=False, indent=1), encoding="utf8")
        summary["exam_rules"] = len(rows)

    # 7. t_version
    if "t_version" in schemas:
        row = con.execute("SELECT * FROM t_version LIMIT 1").fetchone()
        summary["version"] = dict(row) if row else None

    con.close()
    return summary


def main() -> int:
    dbs = sorted(DBS_DIR.glob("*.db"))
    summaries = {}
    for db in dbs:
        prefix = db.stem
        try:
            summaries[prefix] = mine_db(db, prefix)
        except Exception as e:
            summaries[prefix] = {"error": str(e)}
            print(f"[ERR] {prefix}: {e}", file=sys.stderr)

    (OUT_DIR / "summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=1), encoding="utf8")

    # 控制台汇总
    print(f"{'db':<24} {'题目':>6} {'章节':>5} {'媒体':>6} {'媒体类型':>10} {'版本':>18}")
    print("-" * 80)
    for name, s in summaries.items():
        if "error" in s:
            print(f"{name:<24} ERROR: {s['error']}")
            continue
        ver = ""
        if s.get("version"):
            v = s["version"]
            ver = f"{v.get('major_version','?')} {v.get('version','?')}"
        print(f"{name:<24} {s['question_count']:>6} {s['chapter_count']:>5} "
              f"{s['media_count']:>6} {str(s['media_types']):>10} {ver:>18}")
    print(f"\n共 {len(summaries)} 个库，输出到 {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
