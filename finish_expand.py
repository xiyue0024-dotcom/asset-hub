#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
等待深度扩充结束后，自动导出静态站并写一份完成报告。

用法（后台运行）:
    python finish_expand.py
完成后会在项目根目录生成 扩充结果.txt
"""

import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, "data", "library.db")
REPORT = os.path.join(ROOT, "扩充结果.txt")
MAX_WAIT = 90 * 60


def meta(key):
    try:
        conn = sqlite3.connect(DB, timeout=20)
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else ""
    except Exception:
        return ""


def snapshot():
    conn = sqlite3.connect(DB, timeout=20)
    conn.row_factory = sqlite3.Row
    total = conn.execute("SELECT COUNT(*) c FROM photos").fetchone()["c"]
    by_country = conn.execute(
        "SELECT country, COUNT(*) c FROM photos GROUP BY country ORDER BY c DESC").fetchall()
    by_scene = conn.execute(
        "SELECT scene, COUNT(*) c FROM photos GROUP BY scene ORDER BY c DESC").fetchall()
    cities = conn.execute(
        "SELECT COUNT(DISTINCT city) c FROM photos WHERE city != '其他'").fetchone()["c"]
    conn.close()
    return total, by_country, by_scene, cities


def main():
    start_marker = meta("last_expand_at")
    started = time.time()
    print("等待扩充完成… 起始标记 %s" % (start_marker or "(空)"), flush=True)

    while True:
        time.sleep(30)
        now = meta("last_expand_at")
        if now and now != start_marker:
            print("检测到扩充完成: %s" % now, flush=True)
            break
        if time.time() - started > MAX_WAIT:
            print("等待超时，按当前状态导出", flush=True)
            break

    subprocess.run([sys.executable, "build_static.py"], cwd=ROOT)

    total, by_country, by_scene, cities = snapshot()
    lines = [
        "素材库扩充结果",
        "生成时间: %s" % datetime.now().strftime("%Y-%m-%d %H:%M"),
        "",
        "素材总数: %d" % total,
        "覆盖城市: %d 个" % cities,
        "",
        "按国家:",
    ]
    for r in by_country:
        lines.append("  %s  %d" % (r["country"], r["c"]))
    lines.append("")
    lines.append("按场景:")
    for r in by_scene:
        lines.append("  %s  %d" % (r["scene"], r["c"]))
    lines.append("")
    lines.append("静态站已重新导出到 docs/，可直接提交到 GitHub。")

    text = "\n".join(lines)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(text)
    print(text, flush=True)


if __name__ == "__main__":
    main()
