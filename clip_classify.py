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
import urllib.error
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
# 负类用一组「普通照片」的泛描述，而不是单个对照句。
# 单个对照句会让「既不像正类也不像负类」的图被强行判成正类（海滩照被判成车辆产品图）。
NEG_PHOTOS = [
    "a wide landscape or beach scene",
    "a photo of people walking or standing",
    "a photo of food on a table",
    "a photo of a building or street",
    "a photo of an animal or plant",
    "a photo of an indoor room",
]

QUALITY_PROMPTS = {
    "gray": (
        ["a black and white photograph", "a sepia toned old historical photograph",
         "a grayscale monochrome picture"],
        NEG_PHOTOS,
    ),
    "graphic": (
        ["a flat vector illustration or cartoon graphic",
         "a digital drawing, infographic or diagram",
         "a poster with flat colors and text"],
        ["a real photograph taken with a camera"] + NEG_PHOTOS,
    ),
    "sign": (
        ["a close-up photo of a sign, signboard, nameplate or number",
         "a photo dominated by a road sign or shop sign",
         "text painted on a wall or a notice board filling the frame"],
        NEG_PHOTOS,
    ),
    "product": (
        ["a single car or motorcycle photographed alone as a product shot",
         "an isolated vehicle filling the frame on a plain background",
         "a vehicle catalogue photo with no people around"],
        NEG_PHOTOS,
    ),
}

_lock = threading.Lock()
_last = [0.0]
_gap = [1.6]
GAP_MIN = 1.6
# 各标记的判定余量。黑白不走 CLIP——它会把「白墙/灰背景/黑白车身」误判成黑白照，
# 改由像素级饱和度分析判定（图片已在内存里，不额外联网）。
FLAG_MARGIN = {"sign": 0.50, "product": 0.55, "graphic": 0.75}


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
        pos_e, neg_e = encode(pos), encode(neg)
        # 正负提示词拼在一起做一次 softmax，才能公平比较两边概率
        quality[key] = (torch.cat([pos_e, neg_e]), pos_e.shape[0])

    return model, preprocess, scene_names, scene_feat, quality


def fetch_thumb(url, width=250, title=""):
    """取缩略图。优先走 commons 的 thumb.php——它和 upload CDN 是不同的限流池，
    实测成功率 8/8 vs 5/8，是当前最主要的提速手段。"""
    def get(u, timeout=20):
        req = urllib.request.Request(u, headers={"User-Agent": S.UA})
        d = urllib.request.urlopen(req, timeout=timeout).read()
        if len(d) < 1000:
            raise ValueError("too small")
        return d

    if url.lower().endswith((".tiff", ".tif")):
        return None

    channels = []
    if title:
        channels.append(("thumb.php", "https://commons.wikimedia.org/w/thumb.php?f="
                         + urllib.parse.quote(title) + "&w=%d" % width))
    channels.append(("direct", S.thumbify(url, width)))
    channels.append(("wsrv", S.wsrv(url, width)))

    last = "other"
    for name, u in channels:
        try:
            pace()
            data = get(u, 25 if name == "wsrv" else 20)
            # 成功就慢慢把间隔收回来，否则一次失败会把速度永久压在慢档
            _gap[0] = max(GAP_MIN, _gap[0] * 0.97)
            return data, "ok"
        except urllib.error.HTTPError as e:
            # 只有 429/403 才算被限流；404 之类是文件本身的问题，不该拖慢全局
            last = "rate" if e.code in (429, 403) else "other"
            _gap[0] = min(2.5, _gap[0] * 1.4)
            continue
        except Exception:
            last = "other"
            _gap[0] = min(2.5, _gap[0] * 1.4)
            continue
    return None, last


def main():
    limit = None
    retry = False
    scenes = None
    for a in sys.argv[1:]:
        if a == "--retry":
            retry = True
        elif a.startswith("--scenes="):
            scenes = a.split("=", 1)[1].split(",")
        elif a.isdigit():
            limit = int(a)

    conn = S.db()
    S.init_db()
    where = "clip_done IS NULL" if not retry else "1=1"
    if scenes:
        where += " AND scene IN (%s)" % ",".join("'%s'" % x for x in scenes)
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
        data, why = fetch_thumb(r["thumb"], title=r["title"])
        if not data:
            failed += 1
            streak = streak + 1 if why == "rate" else 0
            # 连续被限流才退避，个别坏文件不触发
            if streak >= 6:
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
            sc = model.logit_scale.exp()
            for key, (both, n_pos) in quality.items():
                if key == "gray":
                    continue
                probs = (sc * (f @ both.T)).softmax(dim=-1)[0]
                p_pos = float(probs[:n_pos].sum())
                p_neg = float(probs[n_pos:].sum())
                flags[key] = 1 if p_pos - p_neg > FLAG_MARGIN.get(key, 0.5) else 0

            # 黑白：用像素饱和度判定，比 CLIP 提示词准得多
            flags["gray"] = 0
            try:
                m = S.analyze_color(data)
                flags["gray"] = S.gray_verdict(m)[0]
            except Exception:
                pass

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
