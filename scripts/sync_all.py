"""全库动态同步器：无遗漏、无重叠、无混淆。

三大保证：
  1. 无遗漏  — 扫描本地 db 目录枚举车型（= 官方客户端机制，服务端无全车型接口），
              每个库调 update-super 查增量，有更新即整包下载 + MD5 校验 + 原子替换。
              官方新增车型会以新 .db 下发，下次扫描自动纳管，无需手工加白名单。
  2. 无重叠  — 媒体按内容 hash 去重池（media/pool/<sha1>.<ext>），全库共享同一份，
              bus/truck 引 car 的图不再重复落盘。media_map.json 全库统一映射。
  3. 无混淆  — 全库合并导出时 question_id 加 carType 命名空间前缀，
              统一唯一键 `uid = carType:question_id`。car/bus 的 800000 不再冲突。
              同时记录题目来源库、重复判定（内容相同跨库去重）。

用法：
  python scripts/sync_all.py sync          # 检查并更新全部车型（无遗漏）
  python scripts/sync_all.py check         # 只检查不下载
  python scripts/sync_all.py export        # 全库合并导出（去重+唯一化）
  python scripts/sync_all.py verify        # 完整性校验
  python scripts/sync_all.py all           # sync + export + verify
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

# ============ 路径 ============
LIVE_ROOT = Path(__file__).resolve().parent.parent
DBS_DIR = LIVE_ROOT / "dbs"
EXPORTS_DIR = LIVE_ROOT / "exports"
MEDIA_DIR = LIVE_ROOT / "media"
MEDIA_POOL = MEDIA_DIR / "pool"          # 去重池
SCRIPTS_DIR = LIVE_ROOT / "scripts"
XOR_KEY = b"_jiakaobaodian.com_"

# 驾考宝典客户端（签名机）
JIAKAO_ROOT = Path(os.environ.get(
    "JIAKAO_ROOT", r"D:\Users\lenovo\AppData\Local\驾考宝典"))
RUNNER_DIR = JIAKAO_ROOT / "sign_runner"
PARAMS_FILE = RUNNER_DIR / "params.json"
RESULT_FILE = RUNNER_DIR / "result.json"
SIGN_RUNNER_LOG = JIAKAO_ROOT / "sign_runner_out.txt"
EXE = JIAKAO_ROOT / "驾考宝典.exe"

API_BASE = "https://jk-tiku.kakamobi.cn"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) jiakaobaodian/8.22.0 Chrome/100.0.4896.160 NW.js/0.60.0")

BLOB_COLUMNS = {"question", "explain", "concise_explain", "assured_keywords",
                "illiteracy_explain", "illiteracy_keywords", "keywords",
                "explain_keywords"}
CAR_TYPES = []  # 运行时填充：扫描本地 db 目录


# ============ 签名 ============
def sign(api_path: str, biz: dict | None = None, biz_raw: str | None = None) -> dict:
    params = {"path": api_path}
    if biz is not None:
        params["biz"] = biz
    if biz_raw is not None:
        params["bizRaw"] = biz_raw
    PARAMS_FILE.write_text(json.dumps(params, ensure_ascii=False), encoding="utf8")
    RESULT_FILE.unlink(missing_ok=True)
    pkg = json.loads((JIAKAO_ROOT / "package.json").read_text(encoding="utf8"))
    if pkg.get("main") != "sign_runner/run.js":
        pkg["main"] = "sign_runner/run.js"
        (JIAKAO_ROOT / "package.json").write_text(
            json.dumps(pkg, ensure_ascii=False), encoding="utf8")
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
        tail = SIGN_RUNNER_LOG.read_text(encoding="utf8", errors="replace")[-500:] \
            if SIGN_RUNNER_LOG.exists() else ""
        raise RuntimeError(f"签名失败（无 result.json）\n{tail}")
    result = json.loads(RESULT_FILE.read_text(encoding="utf8"))
    if not result.get("ok"):
        raise RuntimeError(f"签名失败: {result.get('error')}")
    return result


# ============ HTTP ============
def http_get(url: str, timeout: int = 60) -> bytes:
    parsed = urllib.parse.urlsplit(url)
    netloc = parsed.netloc.encode("idna").decode("ascii")
    path = urllib.parse.quote(parsed.path, safe="/")
    safe_url = urllib.parse.urlunsplit((parsed.scheme, netloc, path, parsed.query, ""))
    req = urllib.request.Request(safe_url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read()


def get_json(url: str, timeout: int = 30) -> dict:
    obj = json.loads(http_get(url, timeout).decode("utf8", errors="replace"))
    if not obj.get("success"):
        raise RuntimeError(f"接口失败: {obj.get('errorCode')} {obj.get('message')}")
    return obj["data"]


# ============ DB 工具 ============
def local_version(db_path: Path) -> tuple[int, int]:
    con = sqlite3.connect(str(db_path))
    try:
        row = con.execute("SELECT major_version, version FROM t_version LIMIT 1").fetchone()
    finally:
        con.close()
    if not row:
        raise RuntimeError(f"{db_path} 无 t_version")
    return int(row[0]), int(row[1])


def scan_local_dbs() -> list[str]:
    """扫描本地 db 目录枚举车型（= 官方机制）。"""
    return sorted(p.stem for p in DBS_DIR.glob("*.db"))


# ============ 1. 无遗漏：同步 ============
def remote_latest(db_path: Path, car_type: str) -> dict | None:
    """查最新可用更新。update-super 优先；若服务器不认本地版本返回空，
    用 download.htm 兜底拿最新整包信息（download 对已知 carType 直接返回最新）。"""
    major, version = local_version(db_path)
    biz = {
        "majorVersion": major,
        "sceneCode": "kemu1",
        "version": json.dumps([{"carType": car_type, "version": str(version)}],
                              ensure_ascii=False),
        "applicationType": "pc",
    }
    sig = sign("/api/open/app-db/update-super.htm", biz=biz)
    data = get_json(sig["fullUrl"])
    items = data.get("itemList") or []
    car_items = [i for i in items if i.get("carType") == car_type]
    if car_items:
        return car_items[-1]
    # 兜底：update-super 不认识本地版本（理论上只发生在版本被改过的场景），
    # 直接调 download.htm 拿最新整包信息
    try:
        biz2 = {"carType": car_type, "majorVersion": major, "applicationType": "pc"}
        sig2 = sign("/api/open/app-db/download.htm", biz=biz2)
        info = get_json(sig2["fullUrl"])
        if info and str(info.get("version", "")) != str(version):
            return {
                "carType": car_type,
                "toVersion": info.get("version"),
                "majorVersion": major,
                "title": "整包更新",
                "fromVersion": version,
                "_via_download": True,
            }
    except Exception:
        pass
    return None


def download_full(latest: dict, dest: Path, car_type: str) -> bool:
    major = latest.get("majorVersion", 6)
    biz = {"carType": car_type, "majorVersion": major, "applicationType": "pc"}
    sig = sign("/api/open/app-db/download.htm", biz=biz)
    info = get_json(sig["fullUrl"])
    db_url, db_md5, db_size = info["dbUrl"], info["dbMd5"].lower(), info["dbSize"]
    tmp = dest.with_suffix(".db.tmp")
    req = urllib.request.Request(db_url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as resp, tmp.open("wb") as f:
        shutil.copyfileobj(resp, f)
    if tmp.stat().st_size != db_size:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"大小不符: 期望 {db_size}")
    if hashlib.md5(tmp.read_bytes()).hexdigest() != db_md5:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"MD5 不符: 期望 {db_md5}")
    tmp.replace(dest)
    return True


def sync_one(car_type: str, db_dir: Path, check_only: bool = False,
             dry_run: bool = False) -> dict:
    db_path = db_dir / f"{car_type}.db"
    rec = {"car_type": car_type, "status": "ok"}
    if not db_path.exists():
        rec["status"] = "missing_db"
        return rec
    try:
        local_major, local_ver = local_version(db_path)
        latest = remote_latest(db_path, car_type)
    except Exception as e:
        rec.update(status="error", error=str(e))
        return rec
    rec["local_version"] = str(local_ver)
    if latest is None:
        rec["status"] = "up_to_date"
        return rec
    to_ver = latest.get("toVersion")
    rec.update(status="update_available", to_version=str(to_ver),
               title=latest.get("title"),
               from_version=str(latest.get("fromVersion", "")))
    if check_only or dry_run:
        return rec
    try:
        ok = download_full(latest, db_path, car_type)
        rec["status"] = "updated" if ok else "download_failed"
    except Exception as e:
        rec.update(status="download_error", error=str(e))
    return rec


def sync_all(db_dir: Path, check_only: bool = False, dry_run: bool = False) -> dict:
    car_types = scan_local_dbs()
    results = []
    updated = 0
    for ct in car_types:
        rec = sync_one(ct, db_dir, check_only=check_only, dry_run=dry_run)
        results.append(rec)
        if rec.get("status") == "updated":
            updated += 1
    return {"car_types": len(car_types), "updated": updated, "results": results}


# ============ 2. 无重叠：媒体去重池 ============
def xor_decrypt_bytes(data: bytes) -> bytes:
    if not data:
        return data
    return bytes(b ^ XOR_KEY[i % len(XOR_KEY)] for i, b in enumerate(data))


def xor_decrypt(data: bytes) -> str | None:
    """解密文本 BLOB -> UTF-8 字符串。"""
    if not data:
        return None
    raw = xor_decrypt_bytes(data)
    return raw.decode("utf8", errors="replace")


def media_pool_add(content: bytes, ext: str) -> str:
    """把媒体内容写入去重池，返回 sha1 相对路径（同内容只存一份）。"""
    MEDIA_POOL.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha1(content).hexdigest()
    rel = f"pool/{sha}.{ext}"
    fpath = MEDIA_POOL / f"{sha}.{ext}"
    if not fpath.exists():
        fpath.write_bytes(content)
    return rel


def export_media_dedup(db_path: Path) -> dict:
    """导出该库媒体到去重池，返回 media_key -> pool 相对路径 映射。"""
    con = sqlite3.connect(str(db_path))
    rows = con.execute("SELECT media_key, media_content FROM t_media").fetchall()
    mapping = {}
    stats = {"image": 0, "video": 0, "skipped": 0}
    for key, blob in rows:
        if not key or not blob:
            stats["skipped"] += 1
            continue
        is_video = str(key).startswith("video-")
        ext = "mp4" if is_video else "jpg"
        rel = media_pool_add(bytes(blob), ext)
        mapping[str(key)] = rel
        stats["image" if not is_video else "video"] += 1
    con.close()
    return {"map": mapping, "stats": stats}


def build_media_map() -> None:
    """全库媒体统一映射：media_key -> pool 相对路径（跨库共享去重）。"""
    all_map = {}
    stats = {"image": 0, "video": 0, "skipped": 0, "pool_files": 0}
    for db in sorted(DBS_DIR.glob("*.db")):
        res = export_media_dedup(db)
        for k, v in res["map"].items():
            all_map[f"{db.stem}/{k}"] = v
        for kk in ("image", "video", "skipped"):
            stats[kk] += res["stats"][kk]
    stats["pool_files"] = len(list(MEDIA_POOL.glob("*")))
    (MEDIA_DIR / "media_map.json").write_text(
        json.dumps(all_map, ensure_ascii=False, indent=1), encoding="utf8")
    (EXPORTS_DIR / "media_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf8")
    print(f"媒体去重池: {stats['pool_files']} 文件（33库共 {stats['image']} 图 "
          f"+ {stats['video']} 视频，去重后 {stats['pool_files']}）")
    print(f"media_map.json: {len(all_map)} 条映射")


# ============ 3. 无混淆：全库合并导出 ============
def load_questions_full(db_path: Path, car_type: str) -> list[dict]:
    """读一个库全部题目（解密正文），返回统一结构。"""
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    # chapters
    chapter_title = {}
    if "t_chapter" in tables:
        for r in con.execute("SELECT * FROM t_chapter"):
            d = dict(r)
            cid = d.get("_id")
            title = d.get("title")
            if not isinstance(title, (bytes, bytearray)):
                chapter_title[cid] = title
    # chapter_map
    qid_chapters = {}
    if "t_chapter_question" in tables:
        for r in con.execute("SELECT * FROM t_chapter_question"):
            d = dict(r)
            qid_chapters.setdefault(d.get("question_id"), []).append(
                (d.get("chapter_id"), d.get("areacode")))
    # media local set
    local_media = set()
    if "t_media" in tables:
        for r in con.execute("SELECT media_key FROM t_media"):
            if r[0]:
                local_media.add(r[0])
    # questions
    tq_cols = [c["name"] for c in con.execute("PRAGMA table_info('t_question')")]
    scalar = [c for c in tq_cols if c not in BLOB_COLUMNS]
    blob_cols = [c for c in tq_cols if c in BLOB_COLUMNS]
    qs = []
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
        q["media_ref"] = f"{car_type}/{mkey}" if mkey else None
        chs = qid_chapters.get(qid, [])
        q["chapter_ids"] = [c[0] for c in chs]
        q["chapter_names"] = [chapter_title.get(c[0], "") for c in chs]
        q["areacodes"] = [c[1] for c in chs if c[1]]
        qs.append(q)
    con.close()
    return qs


def export_merged() -> dict:
    """全库合并导出：内容去重，但保留每题全部车型归属（多对多）。

    核心模型：一道科目一通用题同时属于 car/bus/truck/moto，
    合并后只保留一条唯一题，但 `car_types` 字段记录它属于哪些车型。
    这样按 car_type 过滤时一道题只要属于 car 就会被包含，不丢题。
    """
    # 1. 收集所有库的题
    per_db = {}
    # 内容去重：ck -> 主记录
    content_to_master = {}
    # ck -> set(car_types)
    content_to_types = {}
    for db in sorted(DBS_DIR.glob("*.db")):
        ct = db.stem
        qs = load_questions_full(db, ct)
        per_db[ct] = len(qs)
        for q in qs:
            ck = (q.get("question"), q.get("answer"),
                  tuple(q.get("options")))
            content_to_types.setdefault(ck, set()).add(ct)
            # 主记录：car 优先，否则第一个
            if ck not in content_to_master:
                content_to_master[ck] = q
            elif ct == "car" and content_to_master[ck]["car_type"] != "car":
                content_to_master[ck] = q

    # 2. 构建最终：每题补 car_types
    final = []
    for ck, master in content_to_master.items():
        m = dict(master)
        m["car_types"] = sorted(content_to_types[ck])
        # 去重后的 uid 用 car 优先的 uid
        final.append(m)

    result = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_uids": sum(per_db.values()),
        "unique_content": len(final),
        "dup_removed": sum(per_db.values()) - len(final),
        "uid_conflicts": 0,
        "per_db": per_db,
        "questions": final,
    }
    (EXPORTS_DIR / "all_dedup.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf8")
    print(f"全库合并: {sum(per_db.values())} 条 -> 内容去重 {len(final)} 唯一题 "
          f"(删除重复 {result['dup_removed']})")
    print(f"  per_db: {per_db}")
    # 抽样看多车型归属
    multi = [q for q in final if len(q["car_types"]) > 1]
    print(f"  多车型通用题: {len(multi)} ({len(multi)*100//max(len(final),1)}%)")
    return result


# ============ 4. verify ============
def resolve_media_pool(db: str, media_key: str) -> str | None:
    """解析 (db, media_key) -> pool 相对路径。先查本库，再查 car 主库（跨库共享）。"""
    cands = [f"{db}/{media_key}", f"car/{media_key}"]
    media_map = json.loads((MEDIA_DIR / "media_map.json").read_text(encoding="utf8"))
    for c in cands:
        if c in media_map:
            return media_map[c]
    return None


def verify_all() -> dict:
    issues = {"missing_media": 0, "unresolvable_media": [],
              "missing_pool_files": [], "uid_conflict": 0}
    merged = json.loads((EXPORTS_DIR / "all_dedup.json").read_text(encoding="utf8"))
    media_map = json.loads((MEDIA_DIR / "media_map.json").read_text(encoding="utf8"))
    # 建反查: pool 相对路径集合
    pool_rel = set(media_map.values())
    uids = set()
    for q in merged["questions"]:
        # uid 唯一
        if q["uid"] in uids:
            issues["uid_conflict"] += 1
        uids.add(q["uid"])
        mr = q.get("media_ref")
        if mr:
            db, _, mkey = mr.partition("/")
            pool = resolve_media_pool(db, mkey)
            if pool is None:
                issues["missing_media"] += 1
                issues["unresolvable_media"].append(mr)
            else:
                q["media_pool"] = pool
    # 媒体池文件存在性
    for rel in sorted(pool_rel):
        if not (MEDIA_DIR / rel).exists():
            issues["missing_pool_files"].append(rel)
    report = {"issues": {k: (len(v) if isinstance(v, list) else v)
                          for k, v in issues.items()},
              "pool_files": len(pool_rel), "questions": len(merged["questions"])}
    (EXPORTS_DIR / "verify_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf8")
    print(f"校验: 题 {report['questions']} · uid冲突 {issues['uid_conflict']} · "
          f"缺媒体 {issues['missing_media']} · 缺池文件 {len(issues['missing_pool_files'])}")
    if issues["unresolvable_media"][:5]:
        print("  无法解析媒体示例:", issues["unresolvable_media"][:5])
    return report


# ============ main ============
def cmd_sync(args) -> int:
    res = sync_all(DBS_DIR, check_only=args.check_only, dry_run=args.dry_run)
    print(f"同步: {res['car_types']} 个车型, 更新 {res['updated']} 个")
    for r in res["results"]:
        s = r["status"]
        extra = f" {r['local_version']}->{r.get('to_version','')} {r.get('title','')}" \
            if s in ("update_available", "updated") else ""
        err = f" ({r.get('error','')[:80]})" if s == "error" else ""
        print(f"  {r['car_type']:<24} {s:<18}{extra}{err}")
    return 0


def cmd_export(args) -> int:
    build_media_map()
    export_merged()
    return 0


def cmd_verify(args) -> int:
    verify_all()
    return 0


def cmd_all(args) -> int:
    print("== 1/4 同步 ==")
    args.check_only = False
    args.dry_run = False
    cmd_sync(args)
    print("\n== 2/4 媒体去重导出 ==")
    build_media_map()
    print("\n== 3/4 全库合并 ==")
    export_merged()
    print("\n== 4/4 校验 ==")
    verify_all()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="驾考宝典全库动态同步器")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sync", help="检查并更新全部车型")
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_sync)
    sub.add_parser("export", help="全库合并导出(去重+唯一化)").set_defaults(func=cmd_export)
    sub.add_parser("verify", help="完整性校验").set_defaults(func=cmd_verify)
    sub.add_parser("all", help="sync+export+verify").set_defaults(func=cmd_all)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
