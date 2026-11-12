#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram 素材频道红线闸门。

用途：只做一件事——判断一条帖子能不能进素材库。不下载、不落盘、不联网抓图。

设计原则：
1. 默认拒绝。任何一条红线命中即 BLOCK，不做「大部分是好的就放行」这种权衡。
2. 附件类型优先判。出现压缩包/文档/程序，直接 BLOCK，不看正文。
3. 只放行「纯图片 + 生活场景词 + 零红线」这一种组合，其余全部 REVIEW 交人工。
4. 判定依据全部留痕，便于事后复核。

用法：
    python tg_guard.py --demo            # 用内置样本跑一遍，看判定表
    python tg_guard.py --url https://t.me/s/xxx   # 只解析帖子文本，不下载任何图片
    python tg_guard.py --text "正文" --files "a.zip,b.txt"
"""

import argparse
import re
import sys

# ---------------------------------------------------------------------------
# 红线：命中任意一条即 BLOCK。分七类，便于事后统计和审计。
# ---------------------------------------------------------------------------
RED_LINES = {
    "证件身份": [
        "证件", "三方人物", "人物定位", "定位照", "身份证", "护照", "手持",
        "正反面", "人脸", "实名", "kyc", "passport", "id card", "selfie verify",
    ],
    "人设话术": [
        "人设", "话术", "精聊", "深聊", "初聊", "洗脑", "铺垫", "剧本",
        "聊天框架", "情感投资", "杀客", "切客", "养号", "话本",
    ],
    "资金诈骗": [
        "入金", "接盘", "杀猪", "盘口", "开户", "银行卡", "钱包", "usdt",
        "报表", "盈利截图", "出金", "洗钱", "跑分", "代收代付", "汇率差",
    ],
    "引流黑产": [
        "引流", "炒群", "群发", "多开", "号商", "账号购买", "买号", "卖号",
        "p图", "修图神器", "假截图", "改图", "生成截图",
    ],
    "色情低俗": [
        "福利", "无码", "探花", "私密", "裸", "av", "麻豆", "海角", "反差",
    ],
    "翻墙工具": [
        "vpn", "翻墙", "机场", "加速器", "科学上网", "clash", "ssr", "v2ray",
    ],
    "文件类型": [
        ".zip", ".rar", ".7z", ".tar", ".gz", ".txt", ".doc", ".docx",
        ".xls", ".xlsx", ".pdf", ".csv", ".apk", ".exe", ".bat", ".scr",
    ],
}

# 生活场景词：只用来判断「这条帖子像不像生活素材」，不作为放行依据。
LIFE_HINTS = [
    # 中文
    "街拍", "日常", "生活", "随手拍", "菜市场", "巴刹", "芭刹", "组屋", "走廊",
    "地铁", "公交", "医院", "诊所", "学校", "图书馆", "商场", "超市", "咖啡",
    "早餐", "夜市", "海边", "沙滩", "公园", "球场", "理发", "洗衣", "药店",
    # 印尼语 / 马来语
    "warung", "pasar", "kampung", "gang", "kopitiam", "hawker", "void deck",
    "hdb", "klinik", "apotek", "sekolah", "perpustakaan", "stasiun", "mall",
    "laundry", "salon", "bengkel", "sawah", "nelayan", "ojek", "angkot",
    # 英文 / 地名
    "mrt", "hawker centre", "wet market", "food court", "clinic", "polyclinic",
    "library", "void deck", "haji lane", "bugis", "orchard", "tiong bahru",
    "bedok", "yishun", "ang mo kio", "jakarta", "bali", "surabaya", "bandung",
]

# 允许的图片扩展名。除这些以外一律视为非图片附件。
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")

BLOCK, ALLOW, REVIEW = "BLOCK", "ALLOW", "REVIEW"


def _norm(s):
    return (s or "").lower()


def judge(text, files=None):
    """返回 (verdict, reasons, life_hits)。

    files: 附件文件名列表，可为空。
    """
    files = files or []
    t = _norm(text)
    blob = t + " " + " ".join(_norm(f) for f in files)

    reasons = []

    # 1) 附件类型：只要出现非图片附件，直接拦
    for f in files:
        fl = _norm(f)
        if not fl.endswith(IMAGE_EXT):
            reasons.append("非图片附件：%s" % f)

    # 2) 七类红线逐条扫
    for cat, words in RED_LINES.items():
        if cat == "文件类型":
            continue  # 已由附件类型覆盖，正文里出现 .zip 这类字样也补一刀
        hits = [w for w in words if w in blob]
        if hits:
            reasons.append("%s：%s" % (cat, "、".join(hits[:4])))

    # 正文里直接贴出压缩包/文档名的，也算
    for ext in RED_LINES["文件类型"]:
        if ext in t:
            reasons.append("正文含文件类型：%s" % ext)
            break

    life_hits = [w for w in LIFE_HINTS if w in blob]

    if reasons:
        return BLOCK, reasons, life_hits
    if not files:
        # 没有附件（纯文字/纯转发），无法确认是素材，交人工
        return REVIEW, ["无图片附件，无法确认是素材"], life_hits
    if not life_hits:
        return REVIEW, ["有图片但无生活场景词，需人工看图"], life_hits
    return ALLOW, [], life_hits


DEMO = [
    ("#新加坡 哈芝巷 街拍日常", ["IMG_2231.jpg", "IMG_2232.jpg"]),
    ("#新加坡 亚历山大医院 打针", ["IMG_3011.jpg"]),
    ("素材（开户、步骤）", ["素材（开户、步骤）.zip"]),
    ("素材=三方引导入金", ["素材=三方引导入金.zip"]),
    ("1-8天聊天框架 / 7.感情投资洗脑", ["1-8天聊天框架.zip", "7.感情投资洗脑.zip"]),
    ("【亚洲女】素材 照片三方人物定位（H1）", ["【亚洲女】素材 照片三方人物定位（H1）.zip"]),
    ("人设.txt 盘子模版.txt 买卖价格.txt", ["人设.txt", "盘子模版.txt", "买卖价格.txt"]),
    ("引流炒群教程 + Coinbase专业知识和洗脑话术", ["引流炒群教程.zip", "Coinbase专业知识和洗脑话术.docx"]),
    ("#印尼 巴厘岛 泳池很漂亮！房间阳台直面树林", ["IMG_4402.jpg", "IMG_4403.jpg"]),
    ("#澳大利亚接盘 #港股接盘案例", []),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="跑内置样本")
    ap.add_argument("--text", default="", help="帖子正文")
    ap.add_argument("--files", default="", help="附件名，逗号分隔")
    ap.add_argument("--url", default="", help="t.me/s/ 频道页，只解析文本")
    args = ap.parse_args()

    rows = []
    if args.demo:
        rows = DEMO
    elif args.url:
        import urllib.request
        req = urllib.request.Request(args.url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
        # 按「单条消息」切块，再在块内取正文与附件名——不能整页混在一起，
        # 否则一条带 zip 的帖子会把同页所有帖子都判成 BLOCK。
        blocks = re.split(r'(?=<div class="tgme_widget_message[^"]*" data-post=)', html)
        clean = lambda s: re.sub(r"<[^>]+>", " ", s).replace("&quot;", '"').strip()
        for b in blocks:
            if "data-post=" not in b:
                continue
            texts = re.findall(r'tgme_widget_message_text[^>]*>(.*?)</div>', b, re.S)
            docs = re.findall(r'tgme_widget_message_document_title[^>]*>(.*?)</div>', b, re.S)
            text = clean(" ".join(texts))
            files = [clean(d) for d in docs]
            if text or files:
                rows.append((text, files))
    else:
        rows = [(args.text, [f for f in args.files.split(",") if f.strip()])]

    if not rows:
        print("没有可判定的帖子")
        return 1

    counts = {BLOCK: 0, ALLOW: 0, REVIEW: 0}
    print("%-6s %-8s %s" % ("判定", "生活词", "依据 / 正文"))
    print("-" * 92)
    for text, files in rows:
        verdict, reasons, life = judge(text, files)
        counts[verdict] += 1
        head = re.sub(r"\s+", " ", text or "")[:46]
        print("%-6s %-8s %s" % (verdict, len(life), head))
        for r in reasons[:3]:
            print("        └ %s" % r[:80])
    print("-" * 92)
    print("合计：BLOCK %d ｜ ALLOW %d ｜ REVIEW %d"
          % (counts[BLOCK], counts[ALLOW], counts[REVIEW]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
