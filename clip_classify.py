#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 CLIP 零样本分类给素材打标签。

相比手写关键词规则，CLIP 直接「看画面」，能同时解决：
  - 场景分类（美食/建筑/街景/交通…）
  - 黑白照识别
  - 二维插画识别
  - 标识照识别
  - 孤立产品图识别

用法:
    python clip_classify.py            # 处理所有未处理的
    python clip_classify.py 500        # 只处理 500 张
    python clip_classify.py --retry    # 重新处理之前失败的

依赖: torch, open_clip_torch, pillow
"""

import io
import os
import sqlite3
import sys
import threading
import time
import urllib.parse
import urllib.request

import torch
from PIL import Image

import server as S

MODEL_NAME = "ViT-B-32"
PRETRAINED = "laion2b_s34b_b79k"

# 场景标签：一句话描述画面，CLIP 会给每张图打分
SCENE_PROMPTS = {
    "美食": ["a close-up photo of a plate of food",
             "a dish of rice or noodles on a table",
             "a bowl of soup or curry served on a table",
             "satay skewers or fried food on a plate"],
    "用餐": ["people sitting at tables eating in a food court",
             "diners eating inside a restaurant or canteen",
             "a hawker centre with people having a meal",
             "a dining hall with rows of tables and chairs"],
    "咖啡": ["a cup of coffee on a cafe table",
             "the interior of a coffee shop with a counter",
             "a barista making coffee behind a counter"],
    "聚餐": ["a group of people sharing a meal around a table",
             "a buffet spread with many dishes",
             "friends and family eating together"],
    "海滩": ["a sandy beach with the sea and waves",
             "palm trees on a tropical beach",
             "boats on the water near a beach"],
    "自然": ["rice terraces or paddy fields",
             "a mountain, volcano or jungle landscape",
             "a waterfall, lake or river in nature"],
    "建筑": ["the exterior facade of a building",
             "a tall building, tower or apartment block",
             "a row of shophouses or a temple building",
             "a construction site with fencing and hoarding"],
    "交通": ["a road with cars, buses or motorcycles",
             "a train, mrt station or bus terminal",
             "traffic on a street or highway"],
    "人文": ["people wearing traditional costume",
             "a cultural ceremony, dance or festival",
             "people praying or performing a ritual"],
    "街景": ["a street with shops, signs and pedestrians",
             "an alley or market street with stalls",
             "a town square or neighbourhood street"],
    "住宿": ["a hotel room with a bed",
             "a hotel lobby or resort swimming pool",
             "a villa or guesthouse interior"],
    "数码": ["a smartphone or laptop close up",
             "an electronic device on a desk",
             "people using a phone or computer"],
    "标识": ["a close-up of a sign, signboard or plaque",
             "a road sign, shop sign or number plate",
             "text painted on a wall or a notice board"],
}

# 质量标记：每个对应一组正/负描述
QUALITY_PROMPTS = {
    "gray": (
        ["a black and white photograph", "a sepia toned old historical photograph",
         "a grayscale monochrome picture"],
        ["a colorful vibrant photograph", "a photo with bright saturated colors"],
    ),
    "graphic": (
        ["a flat vector illustration or cartoon graphic",
         "a digital drawing, infographic or diagram",
         "a poster with flat colors and text"],
        ["a real photograph taken with a camera"],
    ),
    "sign": (
        ["a close-up photo of a sign, signboard, nameplate or number",
         "a photo dominated by a road sign or shop sign"],
        ["a photo of a wide scene with people and buildings"],
    ),
    "product": (
        ["a single car or motorcycle photographed alone as a product shot",
         "an isolated vehicle on a plain background"],
        ["a street scene with traffic, people and buildings"],
    ),
}

_lock = threading.Lock()
_last = [0.0]
_gap = [2.5]


def pace():
    with _lock:
        wait = _last[0] + _gap[0] - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()


def load_model():
    import open_clip
    model, _, preprocess = open_clip.create_model_and_transforms(
        MODEL_NAME, pretrained=PRETRAINED, cache_dir=os.path.join(os.path.dirname(__file__), "data", "clip")
    )
    model.eval()
    tokenizer = open_clip.get_tokenizer(MODEL_NAME)

    def encode(prompts):
        with torch.no_grad():
            tok = tokenizer(prompts)
            feat = model.encode_text(tok)
            return feat / feat.norm(dim=-1, keepdim=True)

    scene_names = list(SCENE_PROMPTS)
    # 每个类别多句描述，编码后取平均，比单句稳定得多
    scene_feat = torch.stack([
        encode(SCENE_PROMPTS[k]).mean(dim=0) for k in scene_names
    ])
    scene_feat = scene_feat / scene_feat.norm(dim=-1, keepdim=True)

    quality = {}
    for key, (pos, neg) in QUALITY_PROMPTS.items():
        quality[key] = (encode(pos), encode(neg))

    return model, preprocess, scene_names, scene_feat, quality


def fetch_thumb(url, width=250):
    """取 250px 缩略图，直连失败切 wsrv。"""
    for attempt in ("direct", "wsrv"):
        try:
            pace()
            if attempt == "direct":
                if url.lower().endswith((".tiff", ".tif")):
                    raise ValueError("tiff")
                u = S.thumbify(url, width)
                req = urllib.request.Request(u, headers={"User-Agent": S.UA})
                return urllib.request.urlopen(req, timeout=20).read()
            else:
                u = S.wsrv(url, width)
                req = urllib.request.Request(u, headers={"User-Agent": S.UA})
                return urllib.request.urlopen(req, timeout=25).read()
        except Exception:
            _gap[0] = min(3.0, _gap[0] * 1.5)
            continue
    return None


def main():
    limit = None
    retry = False
    for a in sys.argv[1:]:
        if a == "--retry":
            retry = True
        elif a.isdigit():
            limit = int(a)

    conn = S.db()
    S.init_db()
    where = "clip_done IS NULL" if not retry else "1=1"
    # 优先处理最需要分类的：其他场景、餐饮与建筑混淆的
    sql = """SELECT id, thumb, title FROM photos WHERE hidden=0 AND %s
             ORDER BY CASE scene
                        WHEN '其他' THEN 0
                        WHEN '用餐' THEN 1
                        WHEN '美食' THEN 2
                        WHEN '建筑' THEN 3
                        ELSE 4 END, id""" % where
    if limit:
        sql += " LIMIT %d" % limit
    rows = conn.execute(sql).fetchall()
    conn.close()
    print("待分类 %d 张" % len(rows), flush=True)
    if not rows:
        return

    print("加载 CLIP 模型…", flush=True)
    model, preprocess, scene_names, scene_feat, quality = load_model()
    print("模型就绪", flush=True)

    done = failed = streak = 0
    started = time.time()
    for r in rows:
        data = fetch_thumb(r["thumb"])
        if not data:
            failed += 1
            streak += 1
            # 连续失败说明被限流，退避等待而不是空转烧掉队列
            if streak >= 5:
                wait = min(300, 30 * streak)
                print("  连续失败 %d 次，冷却 %d 秒…" % (streak, wait), flush=True)
                time.sleep(wait)
                _gap[0] = min(6.0, _gap[0] * 1.3)
                streak = 0
            continue
        streak = 0
        try:
            img = Image.open(io.BytesIO(data)).convert("RGB")
            x = preprocess(img).unsqueeze(0)
            with torch.no_grad():
                f = model.encode_image(x)
                f = f / f.norm(dim=-1, keepdim=True)
                sims = (model.logit_scale.exp() * (f @ scene_feat.T)).softmax(dim=-1)[0]
            idx = int(sims.argmax())
            score = float(sims[idx])
            # 置信度太低就归到「其他」，避免硬套一个类别
            scene = scene_names[idx] if score >= 0.30 else "其他"

            flags = {}
            for key, (pos, neg) in quality.items():
                sc = model.logit_scale.exp()
                ps = (sc * (f @ pos.T)).softmax(dim=-1)[0].max().item()
                ns = (sc * (f @ neg.T)).softmax(dim=-1)[0].max().item()
                # 要求正类明显胜出，避免模棱两可的图被误标
                flags[key] = 1 if ps - ns > 0.25 else 0

            conn = S.db()
            conn.execute(
                "UPDATE photos SET clip_scene=?, clip_score=?, clip_gray=?, "
                "clip_graphic=?, clip_sign=?, clip_product=?, clip_done=? WHERE id=?",
                (scene, round(score, 3), flags["gray"], flags["graphic"],
                 flags["sign"], flags["product"], int(time.time()), r["id"]),
            )
            conn.commit()
            conn.close()
            done += 1
        except Exception as e:
            failed += 1
            print("  处理失败 id=%s: %s" % (r["id"], str(e)[:40]), flush=True)
            continue

        if done % 100 == 0:
            el = time.time() - started
            print("  已完成 %d/%d，失败 %d，用时 %.0f 分，预计剩余 %.0f 分"
                  % (done, len(rows), failed, el / 60,
                     el / max(done, 1) * (len(rows) - done) / 60), flush=True)

    print("分类完成 %d 张，失败 %d" % (done, failed), flush=True)


if __name__ == "__main__":
    main()
