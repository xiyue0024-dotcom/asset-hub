#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把本地素材库导出为静态站点，用于 GitHub Pages / 任意静态托管。

用法:
    python build_static.py            # 输出到 docs/
    python build_static.py out_dir
"""

import json
import os
import shutil
import sys

import server as S

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "static-site")
STYLE = os.path.join(ROOT, "web", "style.css")
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, "docs")


def main():
    S.init_db()
    conn = S.db()
    rows = conn.execute(
        """SELECT id, title, descr, city, scene, country, orientation,
                  width, height, thumb, page, license, artist,
                  selfie, solo, wm_suspect, blur_score, is_graphic
           FROM photos WHERE hidden=0 ORDER BY id DESC"""
    ).fetchall()
    conn.close()

    items = []
    for r in rows:
        thumb = r["thumb"] or ""
        if not thumb:
            continue
        # 短字段名：索引体积能小四分之一，前端加载时再映射回可读名
        items.append({
            "i": r["id"],
            "t": r["title"] or "",
            "d": (r["descr"] or "")[:80],
            "c": r["city"] or "",
            "s": r["scene"] or "",
            "n": r["country"] or "",
            "o": r["orientation"] or "",
            "w": r["width"] or 0,
            "h": r["height"] or 0,
            "th": thumb,
            "pg": r["page"] or "",
            "li": r["license"] or "",
            "ar": r["artist"] or "",
            "sf": r["selfie"] or 0,
            "so": r["solo"] or 0,
            "wm": r["wm_suspect"] or 0,
            "bl": r["blur_score"],
            "gf": r["is_graphic"] or 0,
        })

    payload = {
        "updated": S.get_meta("last_update_at", ""),
        "total": len(items),
        "items": items,
    }

    data_dir = os.path.join(OUT, "data")
    os.makedirs(data_dir, exist_ok=True)

    # 存成 .js 而不是 .json：GitHub Pages 只对 js/css/html 做 gzip，
    # .json 会原样传输（7.4MB），改成 js 后约 1MB
    js_path = os.path.join(data_dir, "library.js")
    with open(js_path, "w", encoding="utf-8") as f:
        f.write("window.__ASSET_LIB__=")
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";")

    # 清掉旧的 json，避免仓库里留一份 7MB 的无用文件
    old_json = os.path.join(data_dir, "library.json")
    if os.path.exists(old_json):
        os.remove(old_json)

    for name in ("index.html", "app.js"):
        shutil.copyfile(os.path.join(SRC, name), os.path.join(OUT, name))
    shutil.copyfile(STYLE, os.path.join(OUT, "style.css"))

    # GitHub Pages 默认跑 Jekyll，关掉可以加快构建并避免忽略下划线开头的文件
    open(os.path.join(OUT, ".nojekyll"), "w").close()

    size = os.path.getsize(js_path)
    print("导出 %d 条素材" % len(items))
    print("索引文件: %s (%.1f MB)" % (js_path, size / 1024 / 1024))
    print("站点目录: %s" % OUT)
    print("")
    print("本地预览: python -m http.server 8080 --directory %s" % OUT)
    return len(items)


if __name__ == "__main__":
    main()
