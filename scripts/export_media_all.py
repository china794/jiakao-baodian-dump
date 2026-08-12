"""全库媒体导出：每个库的 t_media 媒体 blob 导出到 live/media/<db>/。

media_key 前缀决定类型：image-* -> .jpg，video-* -> .mp4。
media_content 是明文 JPEG/MP4（已验证头 ffd8ff / ftyp），不加密，直接落盘。
输出 media_map.json：media_key -> 本地相对路径。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

DBS_DIR = Path(__file__).resolve().parent.parent / "dbs"
MEDIA_DIR = Path(__file__).resolve().parent.parent / "media"


def export_db(db_path: Path, out_dir: Path) -> dict:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM t_media").fetchall()
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = {"count": 0, "image": 0, "video": 0, "skipped": 0, "errors": 0, "map": {}}
    for r in rows:
        d = dict(r)
        key = d.get("media_key")
        if not key:
            stats["skipped"] += 1
            continue
        blob = d.get("media_content")
        if not blob:
            stats["skipped"] += 1
            continue
        is_video = str(key).startswith("video-")
        ext = ".mp4" if is_video else ".jpg"
        fname = f"{key}{ext}"
        fpath = out_dir / fname
        try:
            fpath.write_bytes(bytes(blob))
            stats["image" if not is_video else "video"] += 1
            stats["map"][key] = f"media/{db_path.stem}/{fname}"
            stats["count"] += 1
        except Exception as e:
            stats["errors"] += 1
            print(f"[ERR] {db_path.stem}/{fname}: {e}", file=sys.stderr)
    con.close()
    return stats


def main() -> int:
    dbs = sorted(DBS_DIR.glob("*.db"))
    all_map = {}
    totals = {"count": 0, "image": 0, "video": 0, "skipped": 0, "errors": 0}
    print(f"{'db':<24} {'导出':>6} {'图':>6} {'视频':>5} {'跳过':>5} {'错误':>5}")
    print("-" * 60)
    for db in dbs:
        try:
            s = export_db(db, MEDIA_DIR / db.stem)
        except Exception as e:
            print(f"{db.stem:<24} ERROR: {e}")
            continue
        print(f"{db.stem:<24} {s['count']:>6} {s['image']:>6} {s['video']:>5} "
              f"{s['skipped']:>5} {s['errors']:>5}")
        for k, v in s["map"].items():
            all_map[f"{db.stem}/{k}"] = v
        for key in ("count", "image", "video", "skipped", "errors"):
            totals[key] += s[key]
    (MEDIA_DIR / "media_map.json").write_text(
        json.dumps(all_map, ensure_ascii=False, indent=1), encoding="utf8")
    print(f"\n合计: 导出 {totals['count']} (图 {totals['image']} / 视频 {totals['video']}), "
          f"跳过 {totals['skipped']}, 错误 {totals['errors']}")
    print(f"media_map.json 已写入 {MEDIA_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
