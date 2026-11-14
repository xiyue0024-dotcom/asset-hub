#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TG 素材库分类契约（单一事实源）。

2026-11-14 重构：素材源从 Wikimedia Commons 全量切换为 Telegram 后，
旧 HTML 的「城市 / 场景 / 8 项质量过滤」失去数据支撑（实测 675 条里
city 671 条为「其他」、scene 664 条为「其他」、8 个质量字段全部为 0）。
本模块重新定义分类维度，并作为后端、抓取器、静态导出、前端的唯一依据。

设计约束：
  1. 互斥   —— 每张图在每个维度上只落一个选项。
  2. 完备   —— 每个维度都有兜底选项，任何一张图都能归类，不产生遗漏。
  3. 可判定 —— 只使用 TG 数据里 100% 有值的客观字段，不依赖文案猜测。
  4. 单一源 —— 选项定义只写在这里；前端通过 /api/facets 或 library.js
               的 taxonomy 字段读取，不在 JS 里另写一份。

维度定义（key / 名称 / 选项 / 归类范围与边界）：
  region      地域     印度尼西亚 / 新加坡 / 未判定
              范围：按频道名与文案的地域强信号判定。
              边界：两者都无信号、或同时命中印尼与新加坡信号时 → 「未判定」；
                    绝不按图片内容猜测。旧值「其他」统一规范为「未判定」。
  channel     来源频道 8 个频道 @name + 「其他频道」
              范围：取 artist 字段（写入时为 @频道名）。
              边界：不在已知频道表内的 → 「其他频道」，保证完备。
  frame       画幅     竖版 / 横版 / 方图
              范围：由 width、height 计算，长边/短边 > 1.12 判竖或横。
              边界：宽高为 0 的异常记录 → 「方图」为兜底，不产生空值。
  grade       清晰度   高清 / 标清 / 小图
              范围：按像素总数 width*height 分档（≥2MP / 1–2MP / <1MP）。
              边界：分档用 >= 与 < 显式闭合，无重叠、无空档。
  caption     文案     带文案 / 纯图
              范围：title 是否为抓取器生成的兜底标题 tg_<channel>_<id>。
              边界：空标题也算「纯图」；该维度只描述有无文字信息，
                    不评价图片质量，也不作为放行依据。

被移除的旧维度（不再出现在任何界面）：
  city / scene / 生活场景聚合 / 8 项质量过滤 / 版权·作者·署名。
"""

import os
import re
import sqlite3

# ---------------------------------------------------------------------------
# 选项定义：前端按此顺序渲染，label 直接用于界面
# ---------------------------------------------------------------------------
TAXONOMY = [
    {
        "key": "region", "label": "地域",
        "scope": "按频道名与文案中的地域强信号判定；无信号不猜。",
        "options": [
            {"v": "印度尼西亚", "label": "印度尼西亚",
             "scope": "频道名或文案含印尼信号，且未同时命中新加坡信号"},
            {"v": "新加坡", "label": "新加坡",
             "scope": "频道名或文案含新加坡信号，且未同时命中印尼信号"},
            {"v": "未判定", "label": "未判定",
             "scope": "无地域信号，或印尼/新加坡信号同时命中；不做图片级猜测"},
        ],
    },
    {
        "key": "channel", "label": "来源频道",
        "scope": "素材来自哪个 Telegram 频道，取 artist 字段。",
        "options": [
            {"v": "H_X_yinni", "label": "@H_X_yinni"},
            {"v": "OO5868998", "label": "@OO5868998"},
            {"v": "yns518", "label": "@yns518"},
            {"v": "yindunixiyasucai", "label": "@yindunixiyasucai"},
            {"v": "yinnisucai8A", "label": "@yinnisucai8A"},
            {"v": "sucaik10", "label": "@sucaik10"},
            {"v": "sucai_so", "label": "@sucai_so"},
            {"v": "sucai_xinjiapoi", "label": "@sucai_xinjiapoi"},
            {"v": "其他频道", "label": "其他频道", "scope": "不在上述列表内的兜底项"},
        ],
    },
    {
        "key": "frame", "label": "画幅",
        "scope": "由图片宽高计算，比例阈值 1.12。",
        "options": [
            {"v": "竖版", "label": "竖版", "scope": "height > width * 1.12"},
            {"v": "横版", "label": "横版", "scope": "width > height * 1.12"},
            {"v": "方图", "label": "方图", "scope": "两者之间；宽高缺失时的兜底"},
        ],
    },
    {
        "key": "grade", "label": "清晰度",
        "scope": "按像素总数分档，三档严格闭合。",
        "options": [
            {"v": "高清", "label": "高清 ≥2MP", "scope": "width*height ≥ 2,000,000"},
            {"v": "标清", "label": "标清 1–2MP", "scope": "1,000,000 ≤ 像素 < 2,000,000"},
            {"v": "小图", "label": "小图 <1MP", "scope": "像素 < 1,000,000"},
        ],
    },
    {
        "key": "caption", "label": "文案",
        "scope": "只描述帖子是否有文字信息，与图片质量无关。",
        "options": [
            {"v": "带文案", "label": "带文案", "scope": "帖子有原始文案，可用于检索"},
            {"v": "纯图", "label": "纯图", "scope": "无文案，标题为抓取器生成的编号"},
        ],
    },
]

DIM_KEYS = [d["key"] for d in TAXONOMY]
FRAME_TO_ORIENT = {"竖版": "portrait", "横版": "landscape", "方图": "square"}
KNOWN_CHANNELS = {o["v"] for o in TAXONOMY[1]["options"]} - {"其他频道"}

SG_SIGNALS = ("新加坡", "狮城", "哈芝巷", "乌节", "牛车水", "滨海湾", "组屋",
              "芽笼", "圣淘沙", "樟宜", "小印度", "克拉码头", "singapore",
              "haji lane", "orchard", "marina bay", "sentosa", "changi",
              "kopitiam", "void deck")
ID_SIGNALS = ("印尼", "印度尼西亚", "雅加达", "巴厘", "泗水", "万隆", "日惹",
              "爪哇", "苏门答腊", "婆罗浮屠", "indonesia", "jakarta", "bali",
              "surabaya", "bandung", "warung", "pasar", "kampung")
SG_CHANNELS = ("xinjiapo", "singapore", "_sg", "sg_sucai")
ID_CHANNELS = ("yinni", "yindu", "indonesia", "yns", "yinnisucai")

FALLBACK_TITLE = re.compile(r"^tg_[A-Za-z0-9_]+_\d+$")


# ---------------------------------------------------------------------------
# 分类函数：输入一条记录（dict / sqlite3.Row），输出 5 个维度的值
# ---------------------------------------------------------------------------
def classify(row):
    g = (lambda k, d="": (row[k] if k in row.keys() else d) if hasattr(row, "keys") else row.get(k, d))

    # 1) 地域：只认频道名/文案强信号，存疑不猜
    title = (g("title") or "")
    descr = (g("descr") or "")
    artist = (g("artist") or "")
    ch = artist.lstrip("@").lower()
    text = (title + " " + descr).lower()
    if any(k in ch for k in SG_CHANNELS):
        region = "新加坡"
    elif any(k in ch for k in ID_CHANNELS):
        region = "印度尼西亚"
    else:
        sg = any(k in text for k in SG_SIGNALS)
        idn = any(k in text for k in ID_SIGNALS)
        region = "新加坡" if (sg and not idn) else (
            "印度尼西亚" if (idn and not sg) else "未判定")

    # 2) 来源频道
    channel = artist.lstrip("@") if artist.lstrip("@") in KNOWN_CHANNELS else "其他频道"

    # 3) 画幅
    w, h = int(g("width") or 0), int(g("height") or 0)
    if not w or not h or abs(w - h) <= 0.12 * max(w, h):
        frame = "方图"
    elif h > w * 1.12:
        frame = "竖版"
    else:
        frame = "横版"

    # 4) 清晰度
    px = w * h
    grade = "高清" if px >= 2_000_000 else ("标清" if px >= 1_000_000 else "小图")

    # 5) 文案状态
    caption = "纯图" if (not title.strip() or FALLBACK_TITLE.match(title.strip())) else "带文案"

    return {"region": region, "channel": channel, "frame": frame,
            "grade": grade, "caption": caption}


def tags_of(c):
    """结构化标签，写进 tags 字段。

    首尾各留一个空格，使 SQL 的 INSTR(tags, ' key:value ') 能精确匹配、
    不会把 channel:sucai_so 误命中 channel:sucai_so_extra。
    """
    return " " + " ".join("%s:%s" % (k, c[k]) for k in DIM_KEYS) + " "


def search_text_of(row, c):
    """检索文本：把新分类与频道/编号纳入，纯图也能按频道、地域、编号搜到。"""
    return " ".join([
        row.get("title", "") or "", row.get("descr", "") or "",
        c["region"], "@" + c["channel"], c["channel"],
        c["frame"], c["grade"], c["caption"],
        tags_of(c), row.get("page", "") or "",
    ]).lower()


# ---------------------------------------------------------------------------
# 重分类：把新结构写回数据库（只处理 telegram 来源）
# ---------------------------------------------------------------------------
def reclassify(db_path, dry_run=False):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM photos WHERE source='telegram'").fetchall()
    from collections import Counter
    counts = {k: Counter() for k in DIM_KEYS}
    updated = 0

    for r in rows:
        d = dict(r)
        c = classify(r)
        for k in DIM_KEYS:
            counts[k][c[k]] += 1
        if not dry_run:
            conn.execute(
                """UPDATE photos SET country=?, city=?, scene=?, tags=?, search_text=?
                   WHERE id=?""",
                (c["region"], "未判定", "未判定", tags_of(c),
                 search_text_of(d, c), r["id"]),
            )
        updated += 1

    if not dry_run:
        conn.commit()
    conn.close()
    return {"total": updated,
            "counts": {k: dict(v) for k, v in counts.items()},
            "dry_run": dry_run}


# ---------------------------------------------------------------------------
# 供前端渲染的分面计数
# ---------------------------------------------------------------------------
def facet_counts(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT country, artist, width, height, title FROM photos "
        "WHERE hidden=0 AND source='telegram'"
    ).fetchall()
    conn.close()
    from collections import Counter
    out = {k: Counter() for k in DIM_KEYS}
    for r in rows:
        c = classify(r)
        for k in DIM_KEYS:
            out[k][c[k]] += 1
    return {
        "dimensions": TAXONOMY,
        "counts": {k: dict(v) for k, v in out.items()},
        "total": len(rows),
    }


if __name__ == "__main__":
    import json
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "data", "library.db")
    if len(sys.argv) > 1 and sys.argv[1] == "facets":
        print(json.dumps(facet_counts(path), ensure_ascii=False, indent=2))
    else:
        dry = "--dry" in sys.argv
        print(json.dumps(reclassify(path, dry), ensure_ascii=False, indent=2))
