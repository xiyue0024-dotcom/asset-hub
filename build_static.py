#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把本地素材库导出为静态站点，用于 GitHub Pages / 任意静态托管。

图片托管两种模式（由 R2_PUBLIC_BASE 决定）：
  1. 未设置  → 原图复制进 docs/tg/，索引写相对路径（本地调试用，仓库会变大）
  2. 已设置  → 原图不进仓库，索引写 <R2_PUBLIC_BASE>/tg/<name> 绝对 URL，
                同时生成 docs/r2-upload-manifest.json 供上传到 R2

R2_PUBLIC_BASE 可来自环境变量，或 config.json 的 "r2_public_base"。
例: https://assets.example.com   （不要带尾斜杠）

用法:
    python build_static.py            # 输出到 docs/
    python build_static.py out_dir
"""

import json
import os
import re
import shutil
import sys

import server as S
import taxonomy

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "static-site")
STYLE = os.path.join(ROOT, "web", "style.css")
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, "docs")


def r2_base():
    """R2 公共访问基址。未配置时返回空串，走本地相对路径模式。"""
    base = os.environ.get("R2_PUBLIC_BASE", "")
    if not base:
        try:
            with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
                base = (json.load(f) or {}).get("r2_public_base", "")
        except Exception:
            base = ""
    return (base or "").rstrip("/")


def main():
    S.init_db()
    conn = S.db()
    # 只导出 >=1MP 的图：前端默认就用 minpx=1000000 过滤，低清图导出去也是白占体积。
    # 尺寸未知（width/height 为 0，如部分外部图库）照常导出。
    # 2026-11-14：移除 Commons 时代的 ≥1MP 导出门槛。TG 素材在抓取时已按
    # 长边 ≥900px 筛选，清晰度改用「清晰度」维度呈现，不再静默过滤掉小图，
    # 否则分类选项会出现「标了 29 张却点不出结果」的遗漏。
    rows = conn.execute(
        """SELECT id, title, descr, city, scene, country, orientation,
                  width, height, thumb, page, license, artist, tags,
                  source, selfie, solo, wm_suspect, blur_score,
                  is_graphic, is_gray, car_iso, junk_sign
           FROM photos
           WHERE hidden=0
           ORDER BY id DESC"""
    ).fetchall()
    conn.close()

    items = []
    for r in rows:
        thumb = r["thumb"] or ""
        if not thumb:
            continue
        # TG 原图是本机 data/tg_photos/ 里的文件（tgfile:// 标记）。
        # 静态站无法解析该协议，导出时复制成 docs/tg/<name> 并改成相对路径。
        if thumb.startswith("tgfile://"):
            thumb = "tg/" + os.path.basename(thumb[len("tgfile://"):])

        # 新分类：由 taxonomy.py 统一计算，前端按维度 key 直接筛选，
        # 不在 JS 里重写一份分类规则。x = 该图在 DIM_KEYS 顺序上的取值。
        c = taxonomy.classify(r)
        tax_vals = [c[k] for k in taxonomy.DIM_KEYS]
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
            "k": r["tags"] or "",
            "sf": r["selfie"] or 0,
            "so": r["solo"] or 0,
            "wm": r["wm_suspect"] or 0,
            "bl": r["blur_score"],
            "gf": r["is_graphic"] or 0,
            "gy": r["is_gray"] or 0,
            "ci": round(r["car_iso"] or 0),
            "jk": r["junk_sign"] or 0,
            "x": tax_vals,
        })

    # 分类契约随索引一起下发：选项、名称、归类范围与边界只在一处定义。
    # 计数按本次实际导出的条目统计，保证「选项显示 N 张」与「点开有 N 张」一致。
    from collections import Counter
    counts = {k: Counter() for k in taxonomy.DIM_KEYS}
    for it in items:
        for k, v in zip(taxonomy.DIM_KEYS, it["x"]):
            counts[k][v] += 1
    payload = {
        "updated": S.get_meta("last_update_at", ""),
        "total": len(items),
        "items": items,
        "taxonomy": taxonomy.TAXONOMY,
        "tax_counts": {k: dict(v) for k, v in counts.items()},
        "tax_keys": taxonomy.DIM_KEYS,
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

    # 把 TG 原图复制进静态站，让 "tg/<name>" 相对路径能解析。
    # 只复制本次索引里真正引用的文件，避免把被红线拦下/低清跳过的图带上线。
    used = {os.path.basename(x["th"]) for x in items if x["th"].startswith("tg/")}
    tg_out = os.path.join(OUT, "tg")
    if used:
        os.makedirs(tg_out, exist_ok=True)
        for name in sorted(used):
            src = os.path.join(S.TG_PHOTOS, name)
            if os.path.isfile(src):
                shutil.copyfile(src, os.path.join(tg_out, name))
        print("TG 图片复制: %d 张 -> %s" % (len(used), tg_out))
    else:
        # 索引里没有 TG 图时清掉旧文件，避免公开站残留已下线的素材
        if os.path.isdir(tg_out):
            for name in os.listdir(tg_out):
                os.remove(os.path.join(tg_out, name))
            os.rmdir(tg_out)

    # 给 library.js 加版本号，避免浏览器/Pages 缓存旧数据
    ver = str(int(os.path.getmtime(js_path)))
    idx = os.path.join(OUT, "index.html")
    with open(idx, encoding="utf-8") as f:
        html = f.read()
    html = re.sub(r"library\.js(\?v=\d+)?", "library.js?v=" + ver, html)
    with open(idx, "w", encoding="utf-8") as f:
        f.write(html)

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
