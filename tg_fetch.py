#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram 生活素材抓取器（仅个人使用）。

设计红线优先：
  1. 每条帖子先过 tg_guard 闸门，只入库 verdict == ALLOW 的生活原图。
  2. BLOCK（命中任一红线）/ REVIEW（疑似、无法确认）一律不入库，仅记审查日志 CSV。
  3. ALLOW 的原图下载后量尺寸，长边 < 下限（默认 900px）视为低清跳过。
  4. 入库走 server.upsert_photo，source_id 唯一去重；tag=telegram，便于检索与治理。

依赖：
  - telethon：仅 --run / --setup 需要（交互登录你的账号一次）。
  - Pillow：测量尺寸（必装）。

配置（二选一）：
  - 环境变量 TG_API_ID / TG_API_HASH
  - 项目内 tg_config.py：TG_API_ID = "..."; TG_API_HASH = "..."

用法：
  python tg_fetch.py --setup                 # 仅登录，生成会话文件
  python tg_fetch.py --run --limit 100       # 抓取并入库（每个频道 limit 条）
  python tg_fetch.py --run --channels sucai_so,sucai_xinjiapoi --limit 50
  python tg_fetch.py --dry                   # 离线验证管线（不联网、不写库）
  python tg_fetch.py --dry --sample x.json   # 用自定义样本离线验证
"""
import argparse
import asyncio
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import server
import tg_guard
import taxonomy
from PIL import Image, ImageFilter, ImageStat

TG_PHOTOS = os.path.join(server.DATA, "tg_photos")
os.makedirs(TG_PHOTOS, exist_ok=True)
SESSION = os.path.join(ROOT, "tg_session.session")

# 你当初给的 8 个频道（可 --channels 覆盖）
CHANNELS = [
    "H_X_yinni", "OO5868998", "yns518", "yindunixiyasucai",
    "yinnisucai8A", "sucaik10", "sucai_so", "sucai_xinjiapoi",
]

MIN_LONG = 900  # 长边下限（px）。960×1280 原图长边 1280 通过；600×800 被跳过。

BLOCK, ALLOW, REVIEW = tg_guard.BLOCK, tg_guard.ALLOW, tg_guard.REVIEW

# 分类规则统一由 taxonomy.py 提供（地域/频道/画幅/清晰度/文案 5 个维度），
# 此处不再维护第二套推断逻辑，避免规则漂移。


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
def load_cfg():
    api_id = os.environ.get("TG_API_ID", "")
    api_hash = os.environ.get("TG_API_HASH", "")
    try:
        import tg_config
        api_id = api_id or getattr(tg_config, "TG_API_ID", "")
        api_hash = api_hash or getattr(tg_config, "TG_API_HASH", "")
    except Exception:
        pass
    return api_id, api_hash


# ---------------------------------------------------------------------------
# 判定 / 测量 / 去重 / 入库
# ---------------------------------------------------------------------------
def seen(sid):
    try:
        c = server.db()
        r = c.execute("SELECT 1 FROM photos WHERE source_id=?", (sid,)).fetchone()
        c.close()
        return bool(r)
    except Exception:
        return False


def measure(path):
    """返回 (w, h, 边缘强度)。边缘强度仅占位参考，noblur 默认开，NULL 也安全。"""
    try:
        im = Image.open(path)
        w, h = im.size
        g = im.convert("L")
        edges = g.filter(ImageFilter.FIND_EDGES)
        score = ImageStat.Stat(edges).mean[0]
        return w, h, round(score, 2)
    except Exception:
        return 0, 0, 0.0


def build_item(channel, msg_id, caption, path, w, h):
    sid = "tg:%s:%s" % (channel, msg_id)
    title = (caption or "").strip() or ("tg_%s_%s" % (channel, msg_id))
    # tgfile:// 标记：服务端 fetch_image 会直接读 data/tg_photos/，前端 proxyUrl 自动走 /img
    turl = "tgfile://" + os.path.basename(path)
    return {
        "source": "telegram",
        "source_id": sid,
        "title": title[:200],
        "descr": (caption or "")[:500],
        "thumb": turl,
        "preview": turl,
        "full": turl,
        "page": "https://t.me/%s/%s" % (channel, msg_id),
        "w": w, "h": h,
        "license": "unknown",
        "artist": "@%s" % channel,
    }


def ingest(channel, msg_id, caption, path, w, h, life_hits):
    """入库一条，并按 taxonomy.py 的新分类结构写入全部分类字段。

    返回 ('SAVED'|'DUP'|'ERR', reason)。
    """
    item = build_item(channel, msg_id, caption, path, w, h)
    cls = taxonomy.classify(item)
    try:
        # upsert_photo 只负责去重与基础字段；分类值随后按契约覆盖，
        # 避免 Commons 时代的 classify()/is_rejected() 再写入旧维度。
        ok = server.upsert_photo(item, cls["region"], taxonomy.tags_of(cls))
    except Exception as e:
        return "ERR", "upsert:%s" % e
    if ok:
        try:
            c = server.db()
            c.execute(
                """UPDATE photos SET cats='telegram', country=?, city=?, scene=?,
                          tags=?, search_text=? WHERE source_id=?""",
                (cls["region"], "未判定", "未判定", taxonomy.tags_of(cls),
                 taxonomy.search_text_of(item, cls), item["source_id"]),
            )
            c.commit(); c.close()
        except Exception:
            pass
        return "SAVED", ""
    return "DUP", "source_id 已存在"


def log_row(writer, channel, msg_id, verdict, reasons, life_n, dim="", saved=""):
    writer.writerow({
        "channel": channel, "msg_id": msg_id, "verdict": verdict,
        "reasons": ";".join(reasons) if isinstance(reasons, list) else reasons,
        "life_hits": life_n, "dim": dim, "saved": saved,
    })


# ---------------------------------------------------------------------------
# 核心：对一条「帖子」做 闸门→下载→量尺寸→入库
#   get_path: 调用时返回本地路径（真实模式异步下载；dry 模式给样本路径）
# ---------------------------------------------------------------------------
async def decide(text, files, channel, msg_id, get_path, writer, dry=False):
    verdict, reasons, life = tg_guard.judge(text or "", files or [])
    if verdict != ALLOW:
        # 红线/待审内容直接返回，绝不调用 get_path —— 不下载、不落盘。
        log_row(writer, channel, msg_id, verdict, reasons, len(life))
        return verdict
    # 放宽放行（纯图无文案）时 reasons 带标记，透传到审查日志便于事后抽查
    mark = list(reasons)
    path = await get_path()
    if not path:
        log_row(writer, channel, msg_id, "NO_MEDIA", mark + ["无法取得文件"], len(life))
        return "NO_MEDIA"
    w, h, _ = measure(path)
    if max(w, h) < MIN_LONG:
        log_row(writer, channel, msg_id, "LOWRES",
                mark + ["%dx%d < %d" % (w, h, MIN_LONG)], len(life), "%dx%d" % (w, h))
        return "LOWRES"
    if dry:
        # 离线验证：判定会通过、尺寸达标，但不写库
        log_row(writer, channel, msg_id, "WOULD_SAVE", mark, len(life),
                "%dx%d" % (w, h), path)
        return "WOULD_SAVE"
    v, why = ingest(channel, msg_id, text, path, w, h, life)
    log_row(writer, channel, msg_id, v, mark + [why], len(life), "%dx%d" % (w, h),
            path if v == "SAVED" else "")
    return v


# ---------------------------------------------------------------------------
# 真实模式（telethon）
# ---------------------------------------------------------------------------
async def setup_only():
    api_id, api_hash = load_cfg()
    if not api_id or not api_hash:
        print("缺少 TG_API_ID / TG_API_HASH，请设置环境变量或 tg_config.py")
        sys.exit(2)
    from telethon import TelegramClient
    client = TelegramClient(SESSION, int(api_id), api_hash)
    await client.start()
    print("会话已保存：%s，可运行 --run" % SESSION)


def known_state(channels, log_path):
    """续抓起点：返回 (每频道已处理的最小 msg_id, 已处理 sid 集合)。

    同时读数据库（已入库）与审查日志（SAVED/BLOCK/LOWRES/DUP 都算处理过），
    保证续抓既不重复下载、也不重复判定同一条消息。
    """
    floors, processed = {}, set()
    try:
        c = server.db()
        for (sid,) in c.execute("SELECT source_id FROM photos WHERE source='telegram'"):
            p = sid.split(":")
            if len(p) >= 3 and p[1] in channels and p[2].isdigit():
                mid = int(p[2])
                floors[p[1]] = min(floors.get(p[1], mid), mid)
                processed.add(sid)
        c.close()
    except Exception:
        pass
    if log_path and os.path.isfile(log_path):
        try:
            with open(log_path, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    ch, mid = row.get("channel", ""), row.get("msg_id", "")
                    if ch in channels and str(mid).isdigit():
                        processed.add("tg:%s:%s" % (ch, mid))
        except Exception:
            pass
    return floors, processed


async def run_channels(channels, limit, delay, writer, continue_mode=False, log_path=None):
    api_id, api_hash = load_cfg()
    if not api_id or not api_hash:
        print("缺少 TG_API_ID / TG_API_HASH，请设置环境变量或 tg_config.py")
        sys.exit(2)
    from telethon import TelegramClient
    client = TelegramClient(SESSION, int(api_id), api_hash)
    await client.start()
    print("登录成功，开始抓取（会话：%s）" % SESSION)

    floors, processed = known_state(channels, log_path) if continue_mode else ({}, set())
    if continue_mode:
        print("增量续抓：以各频道已处理最小消息 ID 为界，只取更早消息")
        for ch in channels:
            print("  @%-20s 起点 < %s" % (ch, floors.get(ch, "无记录")))

    stats = {}
    for ch in channels:
        try:
            entity = await client.get_entity(ch)
        except Exception as e:
            print("跳过频道 %s：%s" % (ch, e))
            continue
        print("== 频道 @%s ==" % ch)
        if continue_mode and ch not in floors:
            print("  无历史记录，跳过（请先跑一次 --run 建立起点）")
            continue
        kw = {"limit": (None if limit <= 0 else limit)}
        if continue_mode:
            # telethon 的 offset_id=X 只返回 id < X 的消息，即更老的消息
            kw["offset_id"] = floors[ch]
        n = 0
        oldest = None
        async for msg in client.iter_messages(entity, **kw):
            oldest = msg.id
            text = msg.message or ""
            files = []
            is_img = False
            ext = ".jpg"
            if msg.photo:
                files = ["photo.jpg"]
                is_img = True
            elif getattr(msg, "document", None):
                name = None
                for a in msg.document.attributes:
                    if hasattr(a, "file_name"):
                        name = a.file_name
                mime = getattr(msg.document, "mime_type", "") or ""
                if mime.startswith("image/"):
                    is_img = True
                files = [name or "doc.bin"]
                ext = os.path.splitext(name or "")[1] or ".jpg"
            if not is_img:
                continue  # 非图片（视频/音频/压缩包）→ 跳过；压缩包本就被闸门拦

            sid = "tg:%s:%s" % (ch, msg.id)
            if sid in processed or seen(sid):
                continue  # 已处理/已入库，绝不重复下载与判定
            processed.add(sid)

            async def get_path(msg=msg, ch=ch, ext=ext):
                p = os.path.join(TG_PHOTOS, "%s_%s%s" % (ch, msg.id, ext))
                try:
                    # telethon 的 download_media 是协程，必须 await；传入显式路径后
                    # 返回实际保存路径（可能与 p 的扩展名不同）。
                    saved = await msg.download_media(p)
                    for cand in (saved, p):
                        if cand and os.path.exists(cand):
                            return cand
                    return None
                except Exception:
                    return None

            v = await decide(text, files, ch, msg.id, get_path, writer)
            stats[v] = stats.get(v, 0) + 1
            n += 1
            if n % 50 == 0:
                print("  @%s 已处理 %d 条（最老 id=%s），本次分布 %s"
                      % (ch, n, oldest, stats), flush=True)
            if delay:
                await asyncio.sleep(delay)
        print("  @%s 结束：处理 %d 条，最老 id=%s" % (ch, n, oldest), flush=True)
    print("抓取完成，本次分布：%s" % stats, flush=True)
    return stats


# ---------------------------------------------------------------------------
# dry 模式：离线验证 闸门→量尺寸→入库判定（不联网、不写库）
# ---------------------------------------------------------------------------
def dry_run(sample_path, writer):
    if sample_path and os.path.exists(sample_path):
        with open(sample_path, encoding="utf-8") as f:
            samples = json.load(f)
    else:
        # 内置样本：覆盖 闸门四类结果 + 低清跳过
        samples = [
            {"channel": "sucai_so", "msg_id": 1,
             "text": "#新加坡 哈芝巷 街拍日常", "filename": "photo.jpg",
             "make": [960, 1280]},
            {"channel": "sucai_so", "msg_id": 2,
             "text": "素材（开户、步骤）", "filename": "素材（开户、步骤）.zip",
             "make": None},
            {"channel": "sucai_so", "msg_id": 3,
             "text": "", "filename": "photo.jpg", "make": [960, 1280]},
            {"channel": "sucai_so", "msg_id": 4,
             "text": "#印尼 巴厘岛 泳池很漂亮", "filename": "photo.jpg",
             "make": [600, 800]},
        ]

    print("== DRY RUN（不联网、不写库）==")
    for s in samples:
        ch = s.get("channel", "demo")
        mid = s.get("msg_id", 0)
        text = s.get("text", "")
        files = [s["filename"]] if s.get("filename") else []
        if s.get("make"):
            w, h = s["make"]
            p = os.path.join(TG_PHOTOS, "dry_%s_%s.jpg" % (ch, mid))
            Image.new("RGB", (w, h), (120, 160, 200)).save(p)
        else:
            p = None

        async def get_path(p=p):
            return p

        v = asyncio.run(decide(text, files, ch, mid, get_path, writer, dry=True))
        print("  @%s/%s -> %s" % (ch, mid, v))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Telegram 生活素材抓取器")
    ap.add_argument("--setup", action="store_true", help="仅登录，生成会话文件")
    ap.add_argument("--run", action="store_true", help="抓取并入库")
    ap.add_argument("--continue", dest="cont", action="store_true",
                    help="增量续抓：从各频道已处理最小消息 ID 往前抓，严格去重")
    ap.add_argument("--dry", action="store_true", help="离线验证管线")
    ap.add_argument("--sample", default="", help="dry 模式的自定义样本 JSON")
    ap.add_argument("--channels", default="", help="逗号分隔频道，覆盖默认列表")
    ap.add_argument("--limit", type=int, default=100,
                    help="每频道抓取条数；--continue 下 0 表示一直抓到频道开头")
    ap.add_argument("--delay", type=float, default=1.0, help="每条间隔（秒）")
    ap.add_argument("--min-long", type=int, default=900, help="长边下限（px）")
    ap.add_argument("--append-log", action="store_true",
                    help="追加写审查日志（续抓时用，不覆盖上次记录）")
    ap.add_argument("--out", default=os.path.join(ROOT, "tg_review.csv"),
                    help="审查日志 CSV")
    args = ap.parse_args()

    global MIN_LONG
    MIN_LONG = args.min_long

    server.init_db()
    # 续抓默认追加日志；覆盖模式才重写表头
    append = args.append_log or args.cont
    mode = "a" if (append and os.path.isfile(args.out) and os.path.getsize(args.out) > 0) else "w"
    logf = open(args.out, mode, newline="", encoding="utf-8")
    cols = ["channel", "msg_id", "verdict", "reasons", "life_hits", "dim", "saved"]
    writer = csv.DictWriter(logf, fieldnames=cols)
    if mode == "w":
        writer.writeheader()

    channels = [c.strip() for c in args.channels.split(",") if c.strip()] or CHANNELS

    try:
        if args.setup:
            asyncio.run(setup_only())
        elif args.run or args.cont:
            # --continue 默认抓到频道开头，除非显式给了 --limit
            lim = 0 if args.cont and args.limit == 100 else args.limit
            asyncio.run(run_channels(channels, lim, args.delay, writer,
                                     continue_mode=args.cont, log_path=args.out))
        elif args.dry:
            dry_run(args.sample, writer)
        else:
            ap.print_help()
    finally:
        logf.close()
        print("审查日志：%s" % args.out)


if __name__ == "__main__":
    main()
