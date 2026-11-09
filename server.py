#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
素材库 · 印尼 / 新加坡生活与旅游素材检索
纯标准库实现：采集适配器 + SQLite 本地库 + 图片缓存代理 + 检索 API

用法:
    python server.py            # 启动服务 http://127.0.0.1:8777
    python server.py ingest     # 命令行批量采集
"""

import hashlib
import html as htmllib
import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, "web")
DATA = os.path.join(ROOT, "data")
CACHE = os.path.join(DATA, "imgcache")
DB = os.path.join(DATA, "library.db")
os.makedirs(CACHE, exist_ok=True)
os.makedirs(WEB, exist_ok=True)

UA = "AssetHub/1.0 (personal material library; local use)"
PORT = 8777

# ----------------------------------------------------------------------------
# 素材来源配置
# ----------------------------------------------------------------------------

def load_config():
    cfg = {
        "pexels_api_key": os.environ.get("PEXELS_API_KEY", ""),
        "unsplash_access_key": os.environ.get("UNSPLASH_ACCESS_KEY", ""),
        "pixabay_api_key": os.environ.get("PIXABAY_API_KEY", ""),
        "flickr_api_key": os.environ.get("FLICKR_API_KEY", ""),
    }
    p = os.path.join(ROOT, "config.json")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                cfg.update(json.load(f) or {})
        except Exception:
            pass
    return cfg


# ----------------------------------------------------------------------------
# 分类规则：国家 / 城市 / 场景
# ----------------------------------------------------------------------------

CITIES = [
    # ---------- 巴厘岛各区（放在父级之前：同分时优先命中更具体的区） ----------
    ("印度尼西亚", "乌布", ["ubud"]),
    ("印度尼西亚", "水明漾", ["seminyak"]),
    ("印度尼西亚", "库塔", ["kuta"]),
    ("印度尼西亚", "勒吉安", ["legian"]),
    ("印度尼西亚", "长谷", ["canggu"]),
    ("印度尼西亚", "沙努尔", ["sanur"]),
    ("印度尼西亚", "金巴兰", ["jimbaran"]),
    ("印度尼西亚", "努沙杜瓦", ["nusa dua"]),
    ("印度尼西亚", "佩尼达岛", ["nusa penida", "penida"]),
    ("印度尼西亚", "乌鲁瓦图", ["uluwatu"]),
    ("印度尼西亚", "海神庙", ["tanah lot"]),
    ("印度尼西亚", "百度库", ["bedugul"]),
    ("印度尼西亚", "德格拉朗", ["tegallalang"]),
    ("印度尼西亚", "金塔马尼", ["kintamani"]),
    ("印度尼西亚", "艾湄", ["amed"]),
    ("印度尼西亚", "罗威纳", ["lovina"]),
    ("印度尼西亚", "席德门", ["sidemen"]),
    ("印度尼西亚", "姆杜克", ["munduk"]),
    ("印度尼西亚", "登巴萨", ["denpasar"]),
    ("印度尼西亚", "巴图尔火山", ["mount batur", "batur"]),
    ("印度尼西亚", "阿贡火山", ["mount agung", "agung"]),
    ("印度尼西亚", "吉利群岛", ["gili trawangan", "gili meno", "gili air", "gili islands"]),
    ("印度尼西亚", "巴厘岛", ["bali"]),

    # ---------- 爪哇 ----------
    ("印度尼西亚", "老城区", ["kota tua"]),
    ("印度尼西亚", "安佐尔", ["ancol"]),
    ("印度尼西亚", "北雅加达", ["north jakarta"]),
    ("印度尼西亚", "中雅加达", ["central jakarta"]),
    ("印度尼西亚", "西雅加达", ["west jakarta"]),
    ("印度尼西亚", "南雅加达", ["south jakarta"]),
    ("印度尼西亚", "东雅加达", ["east jakarta"]),
    ("印度尼西亚", "雅加达", ["jakarta", "monas"]),
    ("印度尼西亚", "日惹", ["yogyakarta", "jogja", "malioboro"]),
    ("印度尼西亚", "婆罗浮屠", ["borobudur"]),
    ("印度尼西亚", "普兰巴南", ["prambanan"]),
    ("印度尼西亚", "万隆", ["bandung"]),
    ("印度尼西亚", "伦邦", ["lembang"]),
    ("印度尼西亚", "覆舟山", ["tangkuban perahu"]),
    ("印度尼西亚", "泗水", ["surabaya"]),
    ("印度尼西亚", "玛琅", ["malang"]),
    ("印度尼西亚", "布罗莫火山", ["bromo"]),
    ("印度尼西亚", "宜珍火山", ["ijen"]),
    ("印度尼西亚", "塞梅鲁火山", ["semeru"]),
    ("印度尼西亚", "梭罗", ["surakarta"]),
    ("印度尼西亚", "三宝垄", ["semarang"]),
    ("印度尼西亚", "卡里蒙爪哇", ["karimunjawa"]),

    # ---------- 苏门答腊 ----------
    ("印度尼西亚", "棉兰", ["medan"]),
    ("印度尼西亚", "多巴湖", ["lake toba", "toba"]),
    ("印度尼西亚", "沙摩西岛", ["samosir"]),
    ("印度尼西亚", "武吉拉旺", ["bukit lawang"]),
    ("印度尼西亚", "班达亚齐", ["banda aceh"]),
    ("印度尼西亚", "巴东", ["padang"]),
    ("印度尼西亚", "巨港", ["palembang"]),
    ("印度尼西亚", "楠榜", ["lampung"]),
    ("印度尼西亚", "勿里洞", ["belitung"]),
    ("印度尼西亚", "邦加勿里洞", ["bangka"]),

    # ---------- 苏拉威西 / 巴布亚 / 努沙登加拉 ----------
    ("印度尼西亚", "望加锡", ["makassar"]),
    ("印度尼西亚", "托拉查", ["toraja"]),
    ("印度尼西亚", "万鸦老", ["manado"]),
    ("印度尼西亚", "布纳肯", ["bunaken"]),
    ("印度尼西亚", "科莫多", ["komodo"]),
    ("印度尼西亚", "弗洛雷斯", ["flores"]),
    ("印度尼西亚", "拉布安巴焦", ["labuan bajo"]),
    ("印度尼西亚", "四王群岛", ["raja ampat", "misool"]),
    ("印度尼西亚", "查亚普拉", ["jayapura"]),
    ("印度尼西亚", "龙目岛", ["lombok", "mataram"]),
    ("印度尼西亚", "松巴哇", ["sumbawa"]),
    ("印度尼西亚", "古邦", ["kupang"]),

    # ---------- 新加坡街区 ----------
    ("新加坡", "滨海湾金沙", ["marina bay sands", "mbs"]),
    ("新加坡", "滨海湾", ["marina bay", "merlion", "esplanade"]),
    ("新加坡", "圣淘沙", ["sentosa", "siloso"]),
    ("新加坡", "乌节路", ["orchard road", "orchard"]),
    ("新加坡", "牛车水", ["chinatown"]),
    ("新加坡", "小印度", ["little india"]),
    ("新加坡", "克拉码头", ["clarke quay"]),
    ("新加坡", "驳船码头", ["boat quay"]),
    ("新加坡", "滨海湾花园", ["gardens by the bay", "supertree"]),
    ("新加坡", "甘榜格南", ["kampong glam", "arab street", "haji lane", "sultan mosque"]),
    ("新加坡", "植物园", ["botanic garden", "orchid garden"]),
    ("新加坡", "樟宜", ["changi"]),
    ("新加坡", "裕廊", ["jurong"]),
    ("新加坡", "武吉士", ["bugis"]),
    ("新加坡", "丹戎巴葛", ["tanjong pagar"]),
    ("新加坡", "加东", ["katong", "joo chiat"]),
    ("新加坡", "荷兰村", ["holland village"]),
    ("新加坡", "登普西山", ["dempsey"]),
    ("新加坡", "河谷", ["river valley"]),
    ("新加坡", "芽笼", ["geylang"]),
    ("新加坡", "马里士他", ["balestier"]),
    ("新加坡", "兀兰", ["woodlands"]),
    ("新加坡", "淡滨尼", ["tampines"]),
    ("新加坡", "榜鹅", ["punggol"]),
    ("新加坡", "盛港", ["sengkang"]),
    ("新加坡", "福康宁", ["fort canning"]),
    ("新加坡", "东海岸", ["east coast park"]),
    ("新加坡", "乌敏岛", ["pulau ubin"]),
    ("新加坡", "麦里芝", ["macritchie"]),
]

SCENES = [
    ("咖啡", ["coffee", "cafe", "cafes", "café", "kopi", "espresso", "latte", "cappuccino",
              "barista", "roastery", "coffeehouse", "coffee shop", "teh tarik",
              "kopitiam", "tea house", "teh", "咖啡", "咖啡馆"]),
    ("聚餐", ["gathering", "feast", "banquet", "celebration", "party", "communal",
              "family dinner", "group dinner", "dinner table", "wedding reception",
              "open house", "hari raya", "reunion", "buffet", "friends eating",
              "family meal", "聚餐", "聚会", "宴席"]),
    ("用餐", ["dining", "diner", "restaurant", "eatery", "warung", "hawker",
              "hawker centre", "food court", "food stall", "canteen", "meal",
              "breakfast", "lunch", "dinner", "supper", "eating", "menu", "waiter",
              "cutlery", "table setting", "dining room", "用餐", "餐厅", "饭桌"]),
    ("海滩", ["beach", "coast", "shore", "seaside", "ocean", "sea", "surf", "island",
              "bay", "lagoon", "sand", "reef", "snorkel", "pier", "jetty"]),
    ("美食", ["food", "dish", "dishes", "cuisine", "satay", "sate", "nasi", "rendang",
              "laksa", "bakso", "soto", "gado", "mie", "bakery", "dessert", "cake",
              "crab", "chicken rice", "kueh", "snack", "juice", "smoothie", "fruit",
              "fried rice", "rice dish", "rice table", "noodle", "soup", "grill",
              "seafood", "curry", "dim sum", "美食", "小吃"]),
    ("住宿", ["hotel", "resort", "villa", "hostel", "guesthouse", "lobby", "pool",
              "suite", "bungalow", "homestay", "bedroom", "resort pool"]),
    ("交通", ["transport", "train", "mrt", "metro", "bus", "tram", "airport", "boat",
              "ferry", "taxi", "jeep", "railway", "station", "terminal", "scooter",
              "tuk tuk", "motorbike", "traffic"]),
    ("人文", ["people", "portrait", "crowd", "festival", "ceremony", "dance", "culture",
              "traditional", "costume", "monk", "worker", "family", "prayer", "ritual",
              "dancer", "musician"]),
    ("建筑", ["architecture", "building", "skyline", "tower", "skyscraper", "temple",
              "mosque", "church", "cathedral", "bridge", "facade", "shophouse",
              "pagoda", "palace", "museum", "monument", "hdb", "flats", "apartment",
              "construction", "hoarding", "scaffold", "estate", "complex", "lobby"]),
    ("自然", ["nature", "mountain", "volcano", "waterfall", "forest", "rice terrace",
              "rice field", "rice fields", "paddy", "paddy field", "jungle", "lake",
              "park", "garden", "cave", "river", "hill", "sunset", "sunrise",
              "landscape", "valley", "cliff"]),
    ("街景", ["street", "alley", "lane", "avenue", "market", "sidewalk", "crossing",
              "neighbourhood", "neighborhood", "town", "village", "plaza", "square",
              "bazaar"]),
    ("数码", ["smartphone", "mobile phone", "handphone", "ponsel", "laptop",
              "komputer", "computer", "tablet", "kamera", "camera", "monitor",
              "keyboard", "printer", "charger", "gadget", "elektronik",
              "electronics", "television", "headphone", "earphone", "router",
              "wifi", "sim card", "power bank"]),
]

COUNTRY_KEYS = {
    "新加坡": ["singapore", "marina bay", "sentosa", "orchard", "changi", "haw par",
               "kampong glam", "clarke quay", "gardens by the bay"],
    "印度尼西亚": ["indonesia", "indonesian", "bali", "jakarta", "java", "sumatra", "lombok",
                   "komodo", "sulawesi", "papua", "borobudur", "prambanan", "bromo", "ubud"],
}


def _build(kws):
    """ASCII 关键词用词边界正则，避免 sea 命中 season、eat 命中 great。"""
    out = []
    for k in kws:
        if re.fullmatch(r"[a-z0-9 \-\u00e9']+", k):
            out.append(re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])"))
        else:
            out.append(k)
    return out


CITY_RX = [(c, city, _build(kws)) for c, city, kws in CITIES]
SCENE_RX = [(name, _build(kws)) for name, kws in SCENES]
COUNTRY_RX = {c: _build(kws) for c, kws in COUNTRY_KEYS.items()}


def _hit(pat, text):
    if isinstance(pat, str):
        return 1 if pat in text else 0
    return 1 if pat.search(text) else 0


def _score2(pats, title, desc):
    """标题命中权重 3，描述命中权重 1——描述里常有噪音（如咖啡种植园提到 coffee）。"""
    s = 0
    for p in pats:
        if _hit(p, title):
            s += 3
        elif _hit(p, desc):
            s += 1
    return s


# 动物名：避免 crab-eating macaque、rice field 这类描述污染餐饮分类
ANIMAL_RX = _build([
    "macaca", "macaque", "monkey", "ape", "gorilla", "orangutan", "bird", "heron",
    "egret", "kingfisher", "sparrow", "dove", "pigeon", "lizard", "gecko",
    "monitor lizard", "insect", "butterfly", "moth", "dragonfly", "snake", "python",
    "squirrel", "cattle", "buffalo", "goat", "rooster", "turtle", "tortoise",
    "frog", "spider", "scorpion", "crab-eating",
])
FOOD_SCENES = ("美食", "用餐", "聚餐", "咖啡")

# 纯「外观」词：只要标题里有，就不该是餐饮场景（不受菜品词影响）
EXTERIOR_RX = _build([
    "building", "exterior", "facade", "construction", "hoarding", "scaffold",
    "junction", "vacant land", "empty plot", "shoplot",
    "single storey", "single-storey", "premises", "street view", "aerial view",
])

# 建筑/外观强信号：标题里有这些词且没有具体菜品词时，餐饮判定作废
BUILDING_RX = _build([
    "building", "block", "hdb", "flats", "apartment", "tower", "skyscraper",
    "facade", "exterior", "construction", "hoarding", "scaffold", "complex",
    "shophouse", "estate", "architecture", "interior of", "lobby", "atrium",
])

# 具体菜品/餐具词：出现这些才算是真正的美食照
DISH_RX = _build([
    "nasi", "satay", "sate", "laksa", "bakso", "soto", "rendang", "gado",
    "mie", "dish", "dishes", "plate", "bowl", "meal", "kueh", "cake", "dessert",
    "curry", "soup", "noodle", "fried rice", "rice dish", "seafood", "dim sum",
    "snack", "bakery", "juice", "smoothie", "grill", "roti", "prata", "kaya",
    "food on", "serving", "platter", "tray of",
])

# 自拍 / 单人人像 / 群体场景 识别
SELFIE_RX = _build([
    "selfie", "self-portrait", "self portrait", "selfie stick", "自拍",
    "me at", "me and", "me with", "my wife", "my husband", "my friend",
    "my family", "us at", "we at",
])
GROUP_RX = _build([
    "group", "crowd", "family", "friends", "people", "gathering", "festival",
    "ceremony", "dance", "dancers", "team", "students", "schoolchildren",
    "buffet", "party", "procession", "parade", "audience", "guests",
    "reception", "wedding", "market", "diners", "customers",
])
SOLO_RX = _build([
    "portrait", "headshot", "posing", "man with", "woman with", "man in",
    "woman in", "a man", "a woman", "young man", "young woman", "old man",
    "old woman", "girl with", "boy with", "lady with", "guy with",
    "man sitting", "woman sitting", "man standing", "woman standing",
    "sitting man", "standing woman", "man wearing", "woman wearing",
    "man holding", "woman holding",
])
PERSON_RX = _build([
    "portrait", "people", "person", "woman", "women", "girl", "boy",
    "tourist", "visitor", "staff", "worker", "vendor", "family", "couple",
    "friends", "group photo", "crowd", "dancer", "monk", "child", "kid",
    "baby", "lady", "guy", "pedestrian", "shopper", "customer", "waiter",
    "chef", "singer", "musician", "pilgrim", "worshipper", "students",
])

# 文件名里的日期戳，常见于相机直接烧录日期的照片
DATE_RX = re.compile(r"\b(?:19|20)\d{2}[-_.]?(?:0[1-9]|1[0-2])[-_.]?(?:0[1-9]|[12]\d|3[01])"
                     r"(?:[ _-]?\d{4,6})?\b")

# ---------------------------------------------------------------------------
# 车辆特写 / 标识照 文本规则
# ---------------------------------------------------------------------------
VEHICLE_RX = _build([
    "mobil", "motor", "automobile", "car park", "parking", "parkir", "showroom",
    "dealer", "bengkel", "cuci mobil", "tempat parkir", "kendaraan", "vehicle",
    "toyota", "honda", "yamaha", "suzuki", "daihatsu", "mitsubishi", "isuzu",
    "kia", "hyundai", "wuling", "chery", "avanza", "ertiga", "nmax", "vario",
    "angkot", "bajaj", "bemo", "ojol", "truk", "truck", "lorry", "taksi", "taxi",
    "lalu lintas", "jalan tol", "expressway",
])

# 产品式机位/特写：判「孤立车辆」最强的文本证据
PRODUCT_SHOT_RX = re.compile(
    r"front view|rear view|side view|rear left|rear right|front left|front right|"
    r"left side|right side|3/4 view|interior|dashboard|engine bay|"
    r"headlight|taillight|wheel|badge|detail|studio|\(cropped\)", re.I)

# 出现这些词说明是场景照，不能判为孤立
# 出现这些词说明是「有场景的车」，不算孤立产品照。注意 parked/parkir 不算场景
CAR_SCENE_RX = _build([
    "street", "jalan", "market", "pasar", "crowd", "people",
    "traffic", "lalu lintas", "highway", "tol", "terminal", "station", "mall",
    "passenger", "penumpang", "driver", "pengemudi",
])

# 标识照：路牌、门牌、店招、柱子编号
SIGN_RX = _build([
    "street sign", "road sign", "traffic sign", "signboard", "shop sign",
    "store sign", "storefront sign", "signage", "nameplate", "plaque",
    "billboard", "notice board", "noticeboard", "directory", "wayfinding",
    "lettering", "typography", "house number", "unit number", "lot number",
    "car park sign", "carpark sign", "basement sign", "level sign",
    "pillar number", "pylon sign", "signpost", "roadside sign",
    "close-up of sign", "close up of sign", "sign close-up", "sign close up",
])

SIGN_CODE_RX = re.compile(r"^[a-z]{0,2}[-_ ]?\d{1,3}[a-z]?$", re.I)

# 弱信号：只有标题很短且不含场景词时才判标识照
SIGN_WEAK_RX = _build(["carpark", "car park", "basement", "pillar", "level b"])
SIGN_SCENE_SAFE = _build(["street scene", "market", "pasar", "crowd", "people",
                          "traffic", "parked", "panorama", "view of"])


def car_flags(title, descr, tags, scene, person):
    """返回 (车辆主题, 孤立特写)。孤立特写=车辆主题+产品式机位+无场景词+无人物。"""
    blob = " ".join([title or "", descr or "", tags or ""]).lower()
    t = (title or "").lower()

    vehicle = any(_hit(p, blob) for p in VEHICLE_RX)
    product = bool(PRODUCT_SHOT_RX.search(t))
    scene_like = any(_hit(p, t) for p in CAR_SCENE_RX)
    # 产品式机位是强证据，但没有它、只要「车辆主题 + 无人物 + 无场景词」也算孤立
    isolated = bool(vehicle and not scene_like and not person)
    return (1 if vehicle else 0), (1 if isolated else 0)


def is_junk_sign(title, descr):
    """标识照：纯编号标题，或标题命中标识词且很短。"""
    t = (title or "").strip()
    tl = t.lower()
    if not tl:
        return 0
    # 纯编号：M31 / H19 / P22 / B2
    stem = re.sub(r"\.(jpe?g|png|gif|webp)$", "", tl).strip()
    if SIGN_CODE_RX.match(stem):
        return 1
    # 命中标识词，且标题很短（避免误伤「街景里带招牌」的长标题）
    if any(_hit(p, tl) for p in SIGN_RX) and len(t) <= 60:
        return 1
    # 弱信号：标题很短 + 无场景词
    if (len(t) <= 35
            and any(_hit(p, tl) for p in SIGN_WEAK_RX)
            and not any(_hit(p, tl) for p in SIGN_SCENE_SAFE)):
        return 1
    return 0


def is_gray_text(title, descr, tags):
    """文本层的黑白线索（命中率极低，仅作补充）。"""
    blob = " ".join([title or "", tags or ""]).lower()
    return 1 if any(_hit(p, blob) for p in _build([
        "black and white", "black-and-white", "monochrome", "grayscale",
        "greyscale", "hitam putih", "b&w photo",
    ])) else 0


def person_flags(title, descr, scene):
    """返回 (自拍, 含人物, 单人人像)。单人人像排除群体场景，避免误杀合影。"""
    t = (title or "").lower()
    d = (descr or "").lower()

    selfie = any(_hit(p, t) or _hit(p, d) for p in SELFIE_RX)
    group = any(_hit(p, t) for p in GROUP_RX)
    solo_kw = any(_hit(p, t) for p in SOLO_RX)
    person = selfie or solo_kw or group or scene == "人文"
    solo = bool(solo_kw and not group and not selfie)

    return (1 if selfie else 0), (1 if person else 0), (1 if solo else 0)


def is_dated(title, descr):
    """标题/描述里带完整日期（YYYYMMDD 或 YYYY-MM-DD）视为可能带日期戳。"""
    return 1 if DATE_RX.search((title or "") + " " + (descr or "")) else 0


def clean_html(s):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", str(s))
    s = htmllib.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _classify_core(title, desc, hint_country=None):
    t = (title or "").lower()
    d = (desc or "").lower()

    country = hint_country
    if not country:
        scores = {c: _score2(p, t, d) for c, p in COUNTRY_RX.items()}
        best = max(scores.values()) if scores else 0
        country = max(scores, key=scores.get) if best > 0 else "印度尼西亚"

    city, city_country, best = "其他", None, 0
    for c_country, c_name, pats in CITY_RX:
        h = _score2(pats, t, d)
        if h > best:
            best, city, city_country = h, c_name, c_country

    if city_country:
        if hint_country and city_country != hint_country:
            # 国家提示与城市冲突：只有强命中才推翻提示
            if best >= 3:
                country = city_country
            else:
                city = "其他"
        else:
            country = city_country

    scene, best = "其他", 0
    for s_name, pats in SCENE_RX:
        h = _score2(pats, t, d)
        if h > best:
            best, scene = h, s_name

    # 标题里出现动物名时，餐饮类判定一律作废
    if scene in FOOD_SCENES and any(_hit(p, t) for p in ANIMAL_RX):
        scene = "自然"

    # 纯外观照：不管有没有菜品词，都不算餐饮
    if scene in FOOD_SCENES and any(_hit(p, t) for p in EXTERIOR_RX):
        scene = "建筑"

    # 标题是建筑/外观、又没有具体菜品词 → 归到建筑，避免"food centre"把楼判成美食
    if (scene in FOOD_SCENES
            and any(_hit(p, t) for p in BUILDING_RX)
            and not any(_hit(p, t) for p in DISH_RX)):
        scene = "建筑"

    # 只有 "market / centre" 这类场所词、没有菜品词 → 归到街景
    if (scene == "美食"
            and not any(_hit(p, t) for p in DISH_RX)
            and any(_hit(p, t) for p in _build(["market", "centre", "center", "hall"]))):
        scene = "街景"

    return country, city, scene


def classify(title, desc="", hint_country=None, fallback=""):
    """标题+描述优先；判不出来时才用采集关键词兜底（避免种子词污染分类）。"""
    country, city, scene = _classify_core(title, desc, hint_country)
    if fallback and (scene == "其他" or city == "其他"):
        _, ci2, s2 = _classify_core(fallback, "", hint_country)
        if scene == "其他" and s2 != "其他":
            scene = s2
        if city == "其他" and ci2 != "其他":
            city = ci2
    return country, city, scene


def orientation_of(w, h):
    if not w or not h:
        return "landscape"
    if w > h * 1.12:
        return "landscape"
    if h > w * 1.12:
        return "portrait"
    return "square"


# 地名歧义黑名单：同名但不在印尼/新加坡的地点
REJECT = ["crete", "greece", "greek", "bali, rajasthan", "bali (india)",
          "bali india", "bali, india", "poster", "stage production", "film still",
          "statelibqld"]

# 二维图形 / 插画：文字线索
GRAPHIC_WORDS = [
    "illustration", "illustrated", "drawing", "vector", "vectorised", "vectorized",
    "cartoon", "clipart", "clip art", "sketch", "artwork", "painting", "watercolor",
    "watercolour", "diagram", "infographic", "chart", "graph", "flat design",
    "icon", "logo", "emblem", "silhouette", "rendering", "3d render", "mockup",
    "map of", "floor plan", "coat of arms", "flag of", "stamp of", "banknote",
]
GRAPHIC_RX = _build(GRAPHIC_WORDS)


def is_graphic_text(text):
    t = (text or "").lower()
    return any(_hit(p, t) for p in GRAPHIC_RX)

# 境外地点黑名单：通用关键词（如 "Singapore cafe"）会捞回全球的结果，这里剔掉
FOREIGN = [
    "manhattan", "brooklyn", "queensland", "australia", "new york", "london", "paris",
    "tokyo", "osaka", "kyoto", "seoul", "bangkok", "thailand", "vietnam", "hanoi",
    "philippines", "manila", "kuala lumpur", "penang", "malaysia", "sri lanka",
    "hong kong", "taiwan", "taipei", "kaohsiung", "tainan", "taichung", "macau",
    "causeway bay", "sai ying pun", "kowloon", "tsim sha tsui",
    "japan", "korea", "germany", "berlin", "france", "italy", "rome", "venice",
    "spain", "madrid", "barcelona", "netherlands", "amsterdam", "portugal",
    "greece", "crete", "turkey", "istanbul", "egypt", "dubai", "uae", "canada",
    "toronto", "brazil", "mexico", "kenya", "morocco", "russia", "moscow", "poland",
    "sweden", "norway", "denmark", "finland", "belgium", "switzerland", "austria",
    "prague", "budapest", "ireland", "dublin", "scotland", "england", "britain",
    "usa", "united states", "america",
    # 中东 / 南亚 / 中亚
    "iran", "tehran", "mashhad", "isfahan", "iraq", "baghdad", "syria", "lebanon",
    "israel", "palestine", "jordan", "saudi", "yemen", "oman", "qatar", "kuwait",
    "bahrain", "afghanistan", "kabul", "pakistan", "karachi", "lahore", "islamabad",
    "bangladesh", "dhaka", "nepal", "kathmandu", "bhutan", "myanmar", "yangon",
    "cambodia", "phnom penh", "laos", "vientiane", "mongolia", "kazakhstan",
    "uzbekistan", "azerbaijan", "georgia country", "armenia",
    # 欧洲其他
    "ukraine", "kiev", "kyiv", "belarus", "serbia", "croatia", "romania", "bulgaria",
    "albania", "macedonia", "bosnia", "slovenia", "slovakia", "lithuania", "latvia",
    "estonia", "iceland", "luxembourg", "malta", "cyprus",
    # 非洲 / 拉美
    "tunisia", "algeria", "libya", "sudan", "ethiopia", "ghana", "nigeria",
    "senegal", "tanzania", "uganda", "zimbabwe", "zambia", "angola", "mozambique",
    "madagascar", "chile", "argentina", "peru", "colombia", "venezuela", "ecuador",
    "bolivia", "uruguay", "paraguay", "cuba", "jamaica", "haiti", "guatemala",
    "honduras", "nicaragua", "costa rica", "panama", "dominican",
]
FOREIGN_RX = _build(FOREIGN)

# 非拉丁文字（西里尔、阿拉伯、泰、天城、韩、日）——印尼/新加坡的照片标题基本是拉丁字母
NONLATIN_RX = re.compile("[\u0400-\u04FF\u0600-\u06FF\u0E00-\u0E7F"
                         "\u0900-\u097F\uAC00-\uD7AF\u3040-\u30FF]")


def has_cjk(text):
    return sum(1 for ch in (text or "") if "\u4e00" <= ch <= "\u9fff") >= 2


# 印尼语 / 马来语特征词：比地名更强的地域信号
LOCAL_WORDS = _build([
    # 功能词（几乎只出现在印尼语/马来语里）
    "yang", "dengan", "untuk", "dari", "pada", "adalah", "tidak", "sudah",
    "karena", "dalam", "oleh", "setelah", "sebelum", "hingga", "sampai",
    "masih", "hanya", "sebuah", "seorang", "banyak", "semua", "antara",
    # 生活名词
    "warung", "makan", "pasar", "jalan", "desa", "kampung", "rumah", "orang",
    "anak", "ibu", "bapak", "sawah", "kebun", "nelayan", "petani", "pedagang",
    "becak", "ojek", "angkot", "masjid", "sekolah", "kota", "kabupaten",
    "kecamatan", "kelurahan", "dusun", "jual", "beli", "dagang", "nasi", "mie",
    "bakso", "soto", "gado", "tempe", "tahu", "sambal", "kerupuk", "kopi",
    "teh", "gula", "minyak", "beras", "sayur", "buah", "ikan", "ayam", "sapi",
    "kambing", "hutan", "gunung", "sungai", "laut", "pantai", "pulau", "danau",
    "tanah", "batu", "kayu", "bambu", "atap", "pintu", "jendela", "kantor",
    "toko", "kedai", "lapak", "gerobak", "pagi", "malam", "siang", "sore",
    # 马来语 / 新加坡本地
    "kopitiam", "makanan", "minuman", "gerai", "bazar", "kampong", "hawker",
])


def has_region_signal(text):
    """地名、或印尼语/马来语词汇，任一命中即认为是目标市场素材。"""
    t = (text or "").lower()
    for _, _, pats in CITY_RX:
        if _score2(pats, t, "") > 0:
            return True
    for pats in COUNTRY_RX.values():
        if _score2(pats, t, "") > 0:
            return True
    return any(_hit(p, t) for p in LOCAL_WORDS)


def is_rejected(text):
    t = (text or "").lower()
    if any(k in t for k in REJECT):
        return True
    if is_graphic_text(t):
        return True
    if FOREIGN_RX and any(_hit(p, t) for p in FOREIGN_RX):
        return True
    # 中文标题但完全没有印尼/新加坡信号：多为港澳台或内地的同题材照片
    if has_cjk(t) and not has_region_signal(t):
        return True
    # 非拉丁文字标题（俄语、阿拉伯语、泰语等）基本不是目标市场
    if NONLATIN_RX.search(text or "") and not has_region_signal(t):
        return True
    return False


def title_key(title):
    """用于去重：同一主题的多张副本归并（含 (1)(2) 与 panoramio 后缀）。"""
    t = re.sub(r"\.[a-z]{2,5}$", "", (title or "").lower())
    t = re.sub(r"\(\s*\d+\s*\)", "", t)
    t = re.sub(r"[-_ ]*panoramio[-_ ]*", "", t)
    t = re.sub(r"[^a-z0-9]+", "", t)
    return t[:80]


# ----------------------------------------------------------------------------
# 数据库
# ----------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL UNIQUE,
    title       TEXT,
    descr       TEXT,
    thumb       TEXT,
    preview     TEXT,
    full        TEXT,
    page        TEXT,
    width       INTEGER,
    height      INTEGER,
    orientation TEXT,
    country     TEXT,
    city        TEXT,
    scene       TEXT,
    tags        TEXT,
    license     TEXT,
    artist      TEXT,
    title_key   TEXT,
    search_text TEXT,
    saved       INTEGER DEFAULT 0,
    created_at  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_country ON photos(country);
CREATE INDEX IF NOT EXISTS idx_city ON photos(city);
CREATE INDEX IF NOT EXISTS idx_scene ON photos(scene);
CREATE INDEX IF NOT EXISTS idx_saved ON photos(saved);
CREATE UNIQUE INDEX IF NOT EXISTS uq_title ON photos(title_key);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# 后续新增字段，老库自动补齐
MIGRATIONS = [
    "ALTER TABLE photos ADD COLUMN blur_score REAL",
    "ALTER TABLE photos ADD COLUMN corner_score REAL",
    "ALTER TABLE photos ADD COLUMN wm_suspect INTEGER DEFAULT 0",
    "ALTER TABLE photos ADD COLUMN hidden INTEGER DEFAULT 0",
    "ALTER TABLE photos ADD COLUMN checked_at INTEGER",
    "ALTER TABLE photos ADD COLUMN selfie INTEGER DEFAULT 0",
    "ALTER TABLE photos ADD COLUMN person INTEGER DEFAULT 0",
    "ALTER TABLE photos ADD COLUMN solo INTEGER DEFAULT 0",
    "ALTER TABLE photos ADD COLUMN dated INTEGER DEFAULT 0",
    "ALTER TABLE photos ADD COLUMN flat REAL",
    "ALTER TABLE photos ADD COLUMN is_graphic INTEGER DEFAULT 0",
    # 黑白 / 车辆特写 / 标识照
    "ALTER TABLE photos ADD COLUMN sat_mean REAL",
    "ALTER TABLE photos ADD COLUMN color_frac REAL",
    "ALTER TABLE photos ADD COLUMN hue_conc REAL",
    "ALTER TABLE photos ADD COLUMN dom_hue INTEGER",
    "ALTER TABLE photos ADD COLUMN mono_corr REAL",
    "ALTER TABLE photos ADD COLUMN is_gray INTEGER DEFAULT 0",
    "ALTER TABLE photos ADD COLUMN sepia INTEGER DEFAULT 0",
    "ALTER TABLE photos ADD COLUMN car_iso REAL",
    "ALTER TABLE photos ADD COLUMN vehicle INTEGER DEFAULT 0",
    "ALTER TABLE photos ADD COLUMN junk_sign INTEGER DEFAULT 0",
    "ALTER TABLE photos ADD COLUMN enrich_at INTEGER",
    "ALTER TABLE photos ADD COLUMN cat_checked INTEGER",
    "ALTER TABLE photos ADD COLUMN cats TEXT",
]

# 质量阈值
MIN_PIXELS = 1000000      # 低于 100 万像素视为低清
BLUR_THRESHOLD = 12.0     # 边缘强度低于此值视为模糊
CORNER_RATIO = 1.9        # 角落边缘密度 / 中心边缘密度，超过则疑似水印

# 黑白判定（先严后宽，改阈值用 recolor 纯 SQL 重算，不重扫）
GRAY_COLOR_FRAC_MAX = 0.03    # 有色像素占比上限
GRAY_SAT_MAX = 20.0           # 平均饱和度上限（0-255）
GRAY_MONO_CORR_MIN = 0.990    # 三通道线性相关下限
GRAY_HUE_CONC_MIN = 0.95      # 色相集中度下限
GRAY_HUE_LO, GRAY_HUE_HI = 8, 48   # 褐调所在色相带
GRAY_SEPIA_SAT_MAX = 90.0

CAR_ISO_THRESHOLD = 60.0      # 孤立车辆得分阈值
SIGN_UNIQ_MAX = 0.30          # 标识照唯一色上限
SIGN_BORDER_DOM_MIN = 0.55    # 标识照边框主色占比下限
SCAN_MIN_INTERVAL = 1.50      # 扫描全局最小请求间隔（秒），低于此值会触发 429


def get_meta(key, default=""):
    try:
        conn = db()
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        conn.close()
        return row["value"] if row else default
    except Exception:
        return default


def set_meta(key, value):
    conn = db()
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def db():
    conn = sqlite3.connect(DB, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.executescript(SCHEMA)
    for sql in MIGRATIONS:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
    conn.close()


def upsert_photo(item, country_hint, tag):
    """写入一条素材。source_id / 标题重复则跳过。返回 True 表示新增。"""
    blob = " ".join([item.get("title", ""), item.get("descr", "")])
    if is_rejected(blob):
        return False

    country, city, scene = classify(item.get("title", ""), item.get("descr", ""),
                                    country_hint, fallback=tag or "")
    selfie, person, solo = person_flags(item.get("title", ""), item.get("descr", ""), scene)
    dated = is_dated(item.get("title", ""), item.get("descr", ""))
    vehicle, car_iso_text = car_flags(item.get("title", ""), item.get("descr", ""),
                                      tag, scene, person)
    junk = is_junk_sign(item.get("title", ""), item.get("descr", ""))
    gray_text = is_gray_text(item.get("title", ""), item.get("descr", ""), tag)
    w, h = item.get("w") or 0, item.get("h") or 0
    tkey = title_key(item.get("title", "")) or item.get("source_id", "")
    search_text = " ".join([
        item.get("title", ""), item.get("descr", ""), tag or "",
        country, city, scene, item.get("license", ""),
    ]).lower()

    conn = db()
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO photos
               (source, source_id, title, descr, thumb, preview, full, page,
                width, height, orientation, country, city, scene, tags,
                license, artist, title_key, search_text,
                selfie, person, solo, dated, vehicle, junk_sign, car_iso,
                is_gray, saved, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)""",
            (
                item["source"], item["source_id"], item.get("title", ""),
                item.get("descr", ""), item.get("thumb", ""), item.get("preview", ""),
                item.get("full", ""), item.get("page", ""), w, h,
                orientation_of(w, h), country, city, scene, tag or "",
                item.get("license", ""), item.get("artist", ""), tkey,
                search_text, selfie, person, solo, dated, vehicle, junk,
                100 if car_iso_text else 0, gray_text, int(time.time()),
            ),
        )
        conn.commit()
        if cur.rowcount > 0:
            _facets_cache.clear()
        return cur.rowcount > 0
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# 适配器：Wikimedia Commons（免密钥）
# ----------------------------------------------------------------------------

def http_get(url, headers=None, timeout=25, retries=4):
    """带 429 退避重试的下载。Wikimedia 对匿名突发请求会限流。"""
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 503):
                wait = 6 * (2 ** i)
                print("   [限流] 等待 %ds 后重试…" % wait, flush=True)
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            last = e
            time.sleep(2)
    raise last


def strip_query(u):
    return (u or "").split("?")[0]


# Wikimedia 只对固定几档宽度生成缩略图，其它宽度直接返回 400
THUMB_SIZES = [250, 500, 960, 1280, 1920]


def snap_width(w):
    for s in THUMB_SIZES:
        if w <= s:
            return s
    return THUMB_SIZES[-1]


def thumbify(url, width):
    """把原图地址转成缩略图地址，宽度对齐到 Wikimedia 允许的档位。"""
    if not url:
        return ""
    width = snap_width(width)
    if "/thumb/" in url:
        return re.sub(r"/\d+px-", "/%dpx-" % width, url, count=1)
    m = re.match(
        r"(https://upload\.wikimedia\.org/wikipedia/commons)/([0-9a-f]/[0-9a-f]{2})/(.+)$", url
    )
    if m:
        base, shard, name = m.group(1), m.group(2), m.group(3)
        return "%s/thumb/%s/%s/%dpx-%s" % (base, shard, name, width, name)
    return url


def pick_urls(full, w):
    """按原图宽度挑选网格缩略图与灯箱预览图，避免请求不存在的放大尺寸。"""
    w = w or 0
    thumb = thumbify(full, 500) if w > 500 else full
    preview = thumbify(full, 1280) if w > 1280 else full
    return thumb, preview


def _parse_pages(raw):
    """把 MediaWiki query.pages 转成统一的素材结构。"""
    out = []
    pages = (raw.get("query") or {}).get("pages") or {}
    for pid, page in pages.items():
        title_raw = page.get("title", "")
        if not title_raw.startswith("File:"):
            continue
        ii = (page.get("imageinfo") or [{}])[0]
        if not ii.get("url"):
            continue
        em = ii.get("extmetadata") or {}
        title = clean_html(title_raw).replace("File:", "")
        full = strip_query(ii.get("url"))
        w, h = ii.get("width") or 0, ii.get("height") or 0
        thumb, preview = pick_urls(full, w)
        out.append({
            "source": "wikimedia",
            "source_id": "wm:%s" % pid,
            "title": title,
            "descr": clean_html(em.get("ImageDescription", {}).get("value", ""))[:400],
            "thumb": thumb,
            "preview": preview,
            "full": full,
            "page": ii.get("descriptionurl", ""),
            "w": w,
            "h": h,
            "license": clean_html(em.get("LicenseShortName", {}).get("value", "")) or "见来源页",
            "artist": clean_html(em.get("Artist", {}).get("value", ""))[:120],
        })
    return out


def wikimedia_search(query, limit=30, offset=0, sort=None):
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": "filetype:bitmap " + query,
        "gsrnamespace": "6", "gsrlimit": str(limit), "gsroffset": str(offset),
        "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": "960",
    }
    if sort:
        params["gsrsort"] = sort
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    try:
        return _parse_pages(json.loads(http_get(url).decode("utf-8")))
    except Exception as e:
        print("[wikimedia] request failed:", e)
        return []


def wikimedia_category(cat, limit=100, cont=None):
    """按分类抓取文件；返回 (素材列表, 下一页游标)。"""
    params = {
        "action": "query", "format": "json", "generator": "categorymembers",
        "gcmtitle": cat, "gcmtype": "file", "gcmlimit": str(limit),
        "gcmsort": "timestamp", "gcmdir": "desc",
        "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": "960",
    }
    if cont:
        params["gcmcontinue"] = cont
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    try:
        raw = json.loads(http_get(url).decode("utf-8"))
    except Exception as e:
        print("[wikimedia] category %s failed: %s" % (cat, e))
        return [], None
    nxt = (raw.get("continue") or {}).get("gcmcontinue")
    return _parse_pages(raw), nxt


def list_subcats(cat, limit=30):
    """列出某个分类下的子分类。"""
    params = {
        "action": "query", "format": "json", "list": "categorymembers",
        "cmtitle": cat, "cmtype": "subcat", "cmlimit": str(limit),
    }
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    try:
        raw = json.loads(http_get(url).decode("utf-8"))
    except Exception as e:
        print("[wikimedia] subcats %s failed: %s" % (cat, e))
        return []
    return [m["title"] for m in (raw.get("query") or {}).get("categorymembers", [])]


# ----------------------------------------------------------------------------
# 适配器：Pexels（需密钥，免费申请）
# ----------------------------------------------------------------------------

def pexels_search(query, limit=30, page=1, key=""):
    if not key:
        return []
    url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": query, "per_page": str(limit), "page": str(page)}
    )
    try:
        raw = json.loads(http_get(url, headers={"Authorization": key}).decode("utf-8"))
    except Exception as e:
        print("[pexels] request failed:", e)
        return []
    out = []
    for p in raw.get("photos", []):
        out.append({
            "source": "pexels",
            "source_id": "px:%s" % p.get("id"),
            "title": (p.get("alt") or "Pexels photo").strip()[:160],
            "descr": p.get("alt") or "",
            "thumb": p.get("src", {}).get("large", ""),
            "preview": p.get("src", {}).get("large2x", ""),
            "full": p.get("src", {}).get("original", ""),
            "page": p.get("url", ""),
            "w": p.get("width") or 0,
            "h": p.get("height") or 0,
            "license": "Pexels License",
            "artist": p.get("photographer", ""),
        })
    return out


# ----------------------------------------------------------------------------
# 适配器：Unsplash（需 Access Key，免费申请）
# ----------------------------------------------------------------------------

def unsplash_search(query, limit=30, page=1, key=""):
    if not key:
        return []
    url = "https://api.unsplash.com/search/photos?" + urllib.parse.urlencode(
        {"query": query, "per_page": str(min(limit, 30)), "page": str(page)}
    )
    try:
        raw = json.loads(http_get(url, headers={"Authorization": "Client-ID " + key}).decode("utf-8"))
    except Exception as e:
        print("[unsplash] request failed:", e)
        return []
    out = []
    for p in raw.get("results", []):
        urls = p.get("urls") or {}
        out.append({
            "source": "unsplash",
            "source_id": "us:%s" % p.get("id"),
            "title": (p.get("description") or p.get("alt_description") or "Unsplash photo")[:160],
            "descr": (p.get("alt_description") or "")[:400],
            "thumb": urls.get("small", ""),
            "preview": urls.get("regular", ""),
            "full": urls.get("full", ""),
            "page": (p.get("links") or {}).get("html", ""),
            "w": p.get("width") or 0,
            "h": p.get("height") or 0,
            "license": "Unsplash License",
            "artist": (p.get("user") or {}).get("name", ""),
        })
    return out


# ----------------------------------------------------------------------------
# 适配器：Pixabay（需 API Key，免费申请）
# ----------------------------------------------------------------------------

def pixabay_search(query, limit=30, page=1, key=""):
    if not key:
        return []
    url = "https://pixabay.com/api/?" + urllib.parse.urlencode({
        "key": key, "q": query, "per_page": str(min(limit, 200)),
        "page": str(page), "image_type": "photo", "safesearch": "true",
    })
    try:
        raw = json.loads(http_get(url).decode("utf-8"))
    except Exception as e:
        print("[pixabay] request failed:", e)
        return []
    out = []
    for p in raw.get("hits", []):
        out.append({
            "source": "pixabay",
            "source_id": "pb:%s" % p.get("id"),
            "title": (p.get("tags") or "Pixabay photo")[:160],
            "descr": (p.get("tags") or "")[:400],
            "thumb": p.get("webformatURL", ""),
            "preview": p.get("largeImageURL", ""),
            "full": p.get("largeImageURL", ""),
            "page": p.get("pageURL", ""),
            "w": p.get("imageWidth") or 0,
            "h": p.get("imageHeight") or 0,
            "license": "Pixabay License",
            "artist": p.get("user", ""),
        })
    return out


# ----------------------------------------------------------------------------
# 适配器：Flickr（真实用户分享，CC 授权子集，需免费 API Key）
# ----------------------------------------------------------------------------

FLICKR_LICENSES = {
    1: "CC BY-NC-SA", 2: "CC BY-NC", 3: "CC BY-NC-ND", 4: "CC BY",
    5: "CC BY-SA", 6: "CC BY-ND", 7: "No known copyright", 9: "CC0",
    10: "Public Domain Mark",
}


def flickr_search(query, limit=30, page=1, key=""):
    """Flickr 的 CC 授权照片：大量普通用户实拍，最接近「真实生活分享」。"""
    if not key:
        return []
    params = {
        "method": "flickr.photos.search", "api_key": key, "format": "json",
        "nojsoncallback": "1", "text": query,
        "license": "1,2,3,4,5,6,9,10",   # 只取 CC 授权
        "per_page": str(min(limit, 100)), "page": str(page),
        "extras": "url_m,url_z,url_c,url_l,owner_name,description,tags,license",
        "sort": "relevance", "content_type": "1",   # 1 = 照片（排除截图/插画）
    }
    url = "https://api.flickr.com/services/rest/?" + urllib.parse.urlencode(params)
    try:
        raw = json.loads(http_get(url).decode("utf-8"))
    except Exception as e:
        print("[flickr] request failed:", e)
        return []
    if raw.get("stat") != "ok":
        print("[flickr] error:", raw.get("message"))
        return []

    out = []
    for p in (raw.get("photos") or {}).get("photo", []):
        pid = p.get("id")
        thumb = p.get("url_m") or p.get("url_z") or ""
        preview = p.get("url_c") or p.get("url_l") or p.get("url_z") or thumb
        full = p.get("url_l") or p.get("url_c") or p.get("url_z") or thumb
        if not thumb:
            continue
        desc = clean_html((p.get("description") or {}).get("_content", ""))
        out.append({
            "source": "flickr",
            "source_id": "fl:%s" % pid,
            "title": (desc or p.get("title") or "Flickr photo")[:160],
            "descr": " ".join([desc, p.get("tags") or ""])[:400],
            "thumb": thumb,
            "preview": preview,
            "full": full,
            "page": "https://www.flickr.com/photos/%s/%s" % (p.get("owner"), pid),
            "w": 0,
            "h": 0,
            "license": FLICKR_LICENSES.get(int(p.get("license") or 0), "CC"),
            "artist": p.get("ownername") or "",
        })
    return out


# ----------------------------------------------------------------------------
# 采集种子
# ----------------------------------------------------------------------------

SEEDS = [
    # ---- 印度尼西亚 ----
    ("Bali beach", "印度尼西亚"), ("Kuta Bali", "印度尼西亚"), ("Ubud Bali", "印度尼西亚"),
    ("Ubud rice terrace", "印度尼西亚"), ("Seminyak Bali", "印度尼西亚"),
    ("Nusa Dua Bali", "印度尼西亚"), ("Uluwatu temple", "印度尼西亚"),
    ("Tanah Lot", "印度尼西亚"), ("Nusa Penida", "印度尼西亚"), ("Sanur Bali", "印度尼西亚"),
    ("Jakarta skyline", "印度尼西亚"), ("Jakarta street", "印度尼西亚"),
    ("Jakarta traffic", "印度尼西亚"), ("Kota Tua Jakarta", "印度尼西亚"),
    ("Borobudur", "印度尼西亚"), ("Prambanan", "印度尼西亚"), ("Yogyakarta", "印度尼西亚"),
    ("Malioboro Yogyakarta", "印度尼西亚"), ("Bandung", "印度尼西亚"),
    ("Lombok beach", "印度尼西亚"), ("Gili islands", "印度尼西亚"),
    ("Komodo dragon", "印度尼西亚"), ("Raja Ampat", "印度尼西亚"),
    ("Mount Bromo", "印度尼西亚"), ("Lake Toba", "印度尼西亚"),
    ("Indonesian food", "印度尼西亚"), ("Nasi goreng", "印度尼西亚"),
    ("Sate ayam", "印度尼西亚"), ("Rendang", "印度尼西亚"),
    ("Indonesian street food", "印度尼西亚"), ("Warung food", "印度尼西亚"),
    ("Balinese dance", "印度尼西亚"), ("Balinese ceremony", "印度尼西亚"),
    ("Indonesian people", "印度尼西亚"), ("Bali resort", "印度尼西亚"),
    ("Bali villa pool", "印度尼西亚"), ("Bali hotel room", "印度尼西亚"),
    ("Jakarta hotel", "印度尼西亚"), ("Jakarta MRT", "印度尼西亚"),
    ("Bali scooter", "印度尼西亚"), ("Indonesian train", "印度尼西亚"),
    ("Bali airport", "印度尼西亚"), ("Indonesian market", "印度尼西亚"),
    ("Bali cafe", "印度尼西亚"),
    # ---- 新加坡 ----
    ("Singapore skyline", "新加坡"), ("Marina Bay Sands", "新加坡"),
    ("Gardens by the Bay", "新加坡"), ("Sentosa", "新加坡"), ("Orchard Road", "新加坡"),
    ("Chinatown Singapore", "新加坡"), ("Little India Singapore", "新加坡"),
    ("Clarke Quay", "新加坡"), ("Kampong Glam", "新加坡"),
    ("Singapore Botanic Gardens", "新加坡"), ("Singapore hawker centre", "新加坡"),
    ("Chilli crab", "新加坡"), ("Hainanese chicken rice", "新加坡"),
    ("Singapore food court", "新加坡"), ("Singapore MRT", "新加坡"),
    ("Singapore street", "新加坡"), ("Singapore hotel", "新加坡"),
    ("Singapore airport", "新加坡"), ("Singapore bus", "新加坡"),
    ("Singapore people", "新加坡"),
]

_ingest_lock = threading.Lock()
_recent_queries = {}
_update_running = False
_facets_cache = {}

# 增量更新用：按 Commons 分类抓最新上传，分类本身精确，不会跑题
CATEGORIES = [
    # ================= 印度尼西亚 · 巴厘岛 =================
    ("Category:Bali", "印度尼西亚"),
    ("Category:Ubud", "印度尼西亚"),
    ("Category:Seminyak", "印度尼西亚"),
    ("Category:Kuta, Bali", "印度尼西亚"),
    ("Category:Legian", "印度尼西亚"),
    ("Category:Canggu", "印度尼西亚"),
    ("Category:Sanur", "印度尼西亚"),
    ("Category:Jimbaran", "印度尼西亚"),
    ("Category:Nusa Dua", "印度尼西亚"),
    ("Category:Nusa Penida", "印度尼西亚"),
    ("Category:Uluwatu", "印度尼西亚"),
    ("Category:Tanah Lot", "印度尼西亚"),
    ("Category:Bedugul", "印度尼西亚"),
    ("Category:Tegallalang", "印度尼西亚"),
    ("Category:Kintamani", "印度尼西亚"),
    ("Category:Amed", "印度尼西亚"),
    ("Category:Lovina", "印度尼西亚"),
    ("Category:Sidemen", "印度尼西亚"),
    ("Category:Munduk", "印度尼西亚"),
    ("Category:Denpasar", "印度尼西亚"),
    ("Category:Beaches of Bali", "印度尼西亚"),
    ("Category:Temples in Bali", "印度尼西亚"),
    ("Category:Rice terraces in Bali", "印度尼西亚"),
    ("Category:Mount Batur", "印度尼西亚"),
    ("Category:Mount Agung", "印度尼西亚"),
    ("Category:Gili Trawangan", "印度尼西亚"),
    ("Category:Gili Meno", "印度尼西亚"),
    ("Category:Gili Air", "印度尼西亚"),

    # ================= 印度尼西亚 · 爪哇 =================
    ("Category:Jakarta", "印度尼西亚"),
    ("Category:North Jakarta", "印度尼西亚"),
    ("Category:Central Jakarta", "印度尼西亚"),
    ("Category:West Jakarta", "印度尼西亚"),
    ("Category:South Jakarta", "印度尼西亚"),
    ("Category:East Jakarta", "印度尼西亚"),
    ("Category:Kota Tua", "印度尼西亚"),
    ("Category:Ancol", "印度尼西亚"),
    ("Category:Yogyakarta", "印度尼西亚"),
    ("Category:Borobudur", "印度尼西亚"),
    ("Category:Prambanan", "印度尼西亚"),
    ("Category:Malioboro", "印度尼西亚"),
    ("Category:Bandung", "印度尼西亚"),
    ("Category:Lembang", "印度尼西亚"),
    ("Category:Tangkuban Perahu", "印度尼西亚"),
    ("Category:Surabaya", "印度尼西亚"),
    ("Category:Malang", "印度尼西亚"),
    ("Category:Mount Bromo", "印度尼西亚"),
    ("Category:Ijen", "印度尼西亚"),
    ("Category:Semeru", "印度尼西亚"),
    ("Category:Surakarta", "印度尼西亚"),
    ("Category:Semarang", "印度尼西亚"),
    ("Category:Karimunjawa", "印度尼西亚"),

    # ================= 印度尼西亚 · 苏门答腊 / 其他 =================
    ("Category:Medan", "印度尼西亚"),
    ("Category:Lake Toba", "印度尼西亚"),
    ("Category:Samosir", "印度尼西亚"),
    ("Category:Bukit Lawang", "印度尼西亚"),
    ("Category:Banda Aceh", "印度尼西亚"),
    ("Category:Padang", "印度尼西亚"),
    ("Category:Palembang", "印度尼西亚"),
    ("Category:Lampung", "印度尼西亚"),
    ("Category:Belitung", "印度尼西亚"),
    ("Category:Bangka Belitung Islands", "印度尼西亚"),

    # ================= 印度尼西亚 · 苏拉威西 / 巴布亚 / 努沙登加拉 =================
    ("Category:Makassar", "印度尼西亚"),
    ("Category:Tana Toraja", "印度尼西亚"),
    ("Category:Manado", "印度尼西亚"),
    ("Category:Bunaken", "印度尼西亚"),
    ("Category:Komodo (island)", "印度尼西亚"),
    ("Category:Flores (Indonesia)", "印度尼西亚"),
    ("Category:Labuan Bajo", "印度尼西亚"),
    ("Category:Raja Ampat", "印度尼西亚"),
    ("Category:Jayapura", "印度尼西亚"),
    ("Category:Lombok", "印度尼西亚"),
    ("Category:Mataram", "印度尼西亚"),
    ("Category:Sumbawa", "印度尼西亚"),
    ("Category:Kupang", "印度尼西亚"),

    # ================= 印度尼西亚 · 主题 =================
    ("Category:Cuisine of Indonesia", "印度尼西亚"),
    ("Category:Balinese cuisine", "印度尼西亚"),
    ("Category:Indonesian cuisine", "印度尼西亚"),
    ("Category:Street food in Indonesia", "印度尼西亚"),
    ("Category:Food of Indonesia", "印度尼西亚"),
    ("Category:Cafés in Indonesia", "印度尼西亚"),
    ("Category:Restaurants in Indonesia", "印度尼西亚"),
    ("Category:Markets in Indonesia", "印度尼西亚"),
    ("Category:Markets in Jakarta", "印度尼西亚"),
    ("Category:Tourism in Indonesia", "印度尼西亚"),
    ("Category:Beaches of Indonesia", "印度尼西亚"),
    ("Category:Volcanoes of Indonesia", "印度尼西亚"),
    ("Category:Hotels in Indonesia", "印度尼西亚"),
    ("Category:Rail transport in Indonesia", "印度尼西亚"),
    ("Category:Airports in Indonesia", "印度尼西亚"),

    # ================= 新加坡 · 街区 =================
    ("Category:Singapore", "新加坡"),
    ("Category:Sentosa", "新加坡"),
    ("Category:Marina Bay", "新加坡"),
    ("Category:Marina Bay Sands", "新加坡"),
    ("Category:Singapore River", "新加坡"),
    ("Category:Clarke Quay", "新加坡"),
    ("Category:Boat Quay", "新加坡"),
    ("Category:Orchard Road, Singapore", "新加坡"),
    ("Category:Chinatown, Singapore", "新加坡"),
    ("Category:Little India, Singapore", "新加坡"),
    ("Category:Kampong Glam", "新加坡"),
    ("Category:Arab Street", "新加坡"),
    ("Category:Haji Lane", "新加坡"),
    ("Category:Bugis, Singapore", "新加坡"),
    ("Category:Tanjong Pagar", "新加坡"),
    ("Category:Katong", "新加坡"),
    ("Category:Joo Chiat", "新加坡"),
    ("Category:Holland Village", "新加坡"),
    ("Category:Dempsey Hill", "新加坡"),
    ("Category:River Valley, Singapore", "新加坡"),
    ("Category:Newton, Singapore", "新加坡"),
    ("Category:Geylang", "新加坡"),
    ("Category:Balestier", "新加坡"),
    ("Category:Jurong", "新加坡"),
    ("Category:Jurong Lake Gardens", "新加坡"),
    ("Category:Woodlands, Singapore", "新加坡"),
    ("Category:Tampines", "新加坡"),
    ("Category:Punggol", "新加坡"),
    ("Category:Sengkang", "新加坡"),
    ("Category:Changi", "新加坡"),

    # ================= 新加坡 · 景点 =================
    ("Category:Jewel Changi Airport", "新加坡"),
    ("Category:Singapore Changi Airport", "新加坡"),
    ("Category:Gardens by the Bay", "新加坡"),
    ("Category:Singapore Botanic Gardens", "新加坡"),
    ("Category:Fort Canning Park", "新加坡"),
    ("Category:East Coast Park", "新加坡"),
    ("Category:Pulau Ubin", "新加坡"),
    ("Category:MacRitchie Reservoir", "新加坡"),
    ("Category:Singapore Zoo", "新加坡"),
    ("Category:Universal Studios Singapore", "新加坡"),
    ("Category:Merlion", "新加坡"),
    ("Category:Esplanade – Theatres on the Bay", "新加坡"),
    ("Category:National Gallery Singapore", "新加坡"),
    ("Category:Singapore Flyer", "新加坡"),

    # ================= 新加坡 · 主题 =================
    ("Category:Hawker centres in Singapore", "新加坡"),
    ("Category:Food of Singapore", "新加坡"),
    ("Category:Cuisine of Singapore", "新加坡"),
    ("Category:Cafés in Singapore", "新加坡"),
    ("Category:Restaurants in Singapore", "新加坡"),
    ("Category:Streets in Singapore", "新加坡"),
    ("Category:Shopping malls in Singapore", "新加坡"),
    ("Category:Parks in Singapore", "新加坡"),
    ("Category:Tourism in Singapore", "新加坡"),
    ("Category:Beaches of Singapore", "新加坡"),
    ("Category:Skyline of Singapore", "新加坡"),
    ("Category:Public housing in Singapore", "新加坡"),
    ("Category:HDB flats", "新加坡"),
    ("Category:Mosques in Singapore", "新加坡"),
    ("Category:Temples in Singapore", "新加坡"),
    ("Category:Churches in Singapore", "新加坡"),
    ("Category:Rail transport in Singapore", "新加坡"),
    ("Category:Hotels in Singapore", "新加坡"),
]


# 日常生活场景：用餐 / 聚餐 / 咖啡 / 饮食
SEEDS_DINING = [
    ("Indonesian restaurant interior", "印度尼西亚"),
    ("warung makan", "印度尼西亚"),
    ("Bali cafe interior", "印度尼西亚"),
    ("Indonesian coffee", "印度尼西亚"),
    ("kopi luwak", "印度尼西亚"),
    ("Balinese family dinner", "印度尼西亚"),
    ("Indonesian family gathering", "印度尼西亚"),
    ("Indonesian wedding feast", "印度尼西亚"),
    ("Indonesian breakfast", "印度尼西亚"),
    ("Indonesian street food stall", "印度尼西亚"),
    ("Bakso", "印度尼西亚"),
    ("Mie goreng", "印度尼西亚"),
    ("Gado-gado", "印度尼西亚"),
    ("Soto ayam", "印度尼西亚"),
    ("Indonesian snacks", "印度尼西亚"),
    ("Indonesian dessert", "印度尼西亚"),
    ("Es campur", "印度尼西亚"),
    ("Indonesian juice drink", "印度尼西亚"),
    ("Jakarta restaurant", "印度尼西亚"),
    ("Jakarta cafe", "印度尼西亚"),
    ("Bali warung food", "印度尼西亚"),
    ("Indonesian dining table", "印度尼西亚"),
    ("Indonesian market food", "印度尼西亚"),
    ("kopitiam Singapore", "新加坡"),
    ("Singapore hawker stall", "新加坡"),
    ("Singapore cafe", "新加坡"),
    ("Singapore coffee shop", "新加坡"),
    ("Singapore teh tarik", "新加坡"),
    ("Singapore kaya toast", "新加坡"),
    ("Singapore breakfast", "新加坡"),
    ("Singapore restaurant interior", "新加坡"),
    ("Singapore family dinner", "新加坡"),
    ("Singapore dim sum", "新加坡"),
    ("Singapore dessert", "新加坡"),
    ("Singapore drinks", "新加坡"),
    ("Singapore people eating", "新加坡"),
    ("Singapore food stall", "新加坡"),
    ("Singapore dining", "新加坡"),
]


def ingest_query(query, country_hint=None, limit=30, sort=None):
    added = 0
    for item in wikimedia_search(query, limit=limit, sort=sort):
        if upsert_photo(item, country_hint, query):
            added += 1
    cfg = load_config()
    if cfg.get("pexels_api_key"):
        for item in pexels_search(query, limit=limit, key=cfg["pexels_api_key"]):
            if upsert_photo(item, country_hint, query):
                added += 1
    if cfg.get("unsplash_access_key"):
        for item in unsplash_search(query, limit=limit, key=cfg["unsplash_access_key"]):
            if upsert_photo(item, country_hint, query):
                added += 1
    if cfg.get("pixabay_api_key"):
        for item in pixabay_search(query, limit=limit, key=cfg["pixabay_api_key"]):
            if upsert_photo(item, country_hint, query):
                added += 1
    if cfg.get("flickr_api_key"):
        for item in flickr_search(query, limit=limit, key=cfg["flickr_api_key"]):
            if upsert_photo(item, country_hint, query):
                added += 1
    return added


def ingest_all(limit=50):
    total = 0
    for i, (q, country) in enumerate(SEEDS, 1):
        n = ingest_query(q, country, limit=limit)
        total += n
        print("[%02d/%d] %-32s +%d" % (i, len(SEEDS), q, n), flush=True)
        time.sleep(1.8)
    print("done, total new: %d" % total, flush=True)
    return total


def ingest_dining(limit=50):
    total = 0
    for i, (q, country) in enumerate(SEEDS_DINING, 1):
        n = ingest_query(q, country, limit=limit)
        total += n
        print("[%02d/%d] %-32s +%d" % (i, len(SEEDS_DINING), q, n), flush=True)
        time.sleep(1.8)
    print("done, total new: %d" % total, flush=True)
    return total


def reclassify_all():
    """用最新规则重算已有素材的国家/城市/场景，不重新下载图片。"""
    conn = db()
    rows = conn.execute("SELECT id, title, descr, tags, country FROM photos").fetchall()
    n = 0
    for r in rows:
        country, city, scene = classify(r["title"] or "", r["descr"] or "",
                                        r["country"], fallback=r["tags"] or "")
        selfie, person, solo = person_flags(r["title"], r["descr"], scene)
        dated = is_dated(r["title"], r["descr"])
        vehicle, car_iso_text = car_flags(r["title"], r["descr"], r["tags"], scene, person)
        junk = is_junk_sign(r["title"], r["descr"])
        gray_text = is_gray_text(r["title"], r["descr"], r["tags"])
        search_text = " ".join([
            r["title"] or "", r["descr"] or "", r["tags"] or "",
            country, city, scene,
        ]).lower()
        conn.execute(
            "UPDATE photos SET country=?, city=?, scene=?, search_text=?, "
            "selfie=?, person=?, solo=?, dated=?, vehicle=?, junk_sign=?, "
            "car_iso=MAX(COALESCE(car_iso,0), ?), "
            "is_gray=MAX(COALESCE(is_gray,0), ?) WHERE id=?",
            (country, city, scene, search_text, selfie, person, solo, dated,
             vehicle, junk, 100 if car_iso_text else 0, gray_text, r["id"]),
        )
        n += 1
    conn.commit()
    conn.close()
    print("reclassified %d rows" % n, flush=True)
    return n


def purge_rejected():
    """删除与印尼/新加坡无关、或地名歧义的素材（已入库的历史数据）。"""
    conn = db()
    rows = conn.execute("SELECT id, title, descr, tags FROM photos").fetchall()
    killed = 0
    for r in rows:
        blob = " ".join([r["title"] or "", r["descr"] or "", r["tags"] or ""])
        if is_rejected(blob):
            conn.execute("DELETE FROM photos WHERE id=?", (r["id"],))
            killed += 1
    conn.commit()
    left = conn.execute("SELECT COUNT(*) c FROM photos").fetchone()["c"]
    conn.close()
    print("purged %d rows, %d left" % (killed, left), flush=True)
    return killed


def refix_thumbs():
    """按 Wikimedia 允许的尺寸重算已入库素材的缩略图地址。"""
    conn = db()
    rows = conn.execute("SELECT id, full, width FROM photos").fetchall()
    n = 0
    for r in rows:
        full = r["full"] or ""
        if not full:
            continue
        thumb, preview = pick_urls(full, r["width"])
        conn.execute("UPDATE photos SET thumb=?, preview=? WHERE id=?",
                     (thumb, preview, r["id"]))
        n += 1
    conn.commit()
    conn.close()
    print("refixed %d thumbs" % n, flush=True)
    return n


def update_latest(limit=100, pause=3.0):
    """增量更新：按分类抓取最新上传的素材，已入库的自动跳过。"""
    total = 0
    started = time.time()
    for i, (cat, country) in enumerate(CATEGORIES, 1):
        items, _ = wikimedia_category(cat, limit)
        n = 0
        for it in items:
            if upsert_photo(it, country, cat):
                n += 1
        total += n
        print("[%02d/%d] %-38s 取回%2d 新增%2d" % (i, len(CATEGORIES), cat, len(items), n),
              flush=True)
        time.sleep(pause)
    set_meta("last_update_at", datetime.now().strftime("%Y-%m-%d %H:%M"))
    set_meta("last_update_added", str(total))
    set_meta("last_update_seconds", str(int(time.time() - started)))
    print("update done, +%d new in %ds" % (total, time.time() - started), flush=True)
    return total


def scheduler_loop(hour=7):
    """服务常驻时，每天在指定小时执行一次增量更新。"""
    print("[scheduler] 每日 %02d:00 自动更新已启用" % hour, flush=True)
    while True:
        try:
            now = datetime.now()
            last = get_meta("last_update_at", "")
            done_today = last.startswith(now.strftime("%Y-%m-%d"))
            if now.hour >= hour and not done_today:
                print("[scheduler] 开始每日增量更新…", flush=True)
                with _ingest_lock:
                    update_latest()
        except Exception as e:
            print("[scheduler] 出错: %s" % e, flush=True)
        time.sleep(600)


def analyze_image(data):
    """返回 (清晰度, 角落边缘比)。清晰度越低越模糊；角落比越高越可能带水印。"""
    import io

    from PIL import Image, ImageFilter, ImageStat

    im = Image.open(io.BytesIO(data)).convert("L")
    im.thumbnail((320, 320))
    w, h = im.size
    if w < 40 or h < 40:
        return 0.0, 1.0

    edges = im.filter(ImageFilter.FIND_EDGES)
    blur = ImageStat.Stat(edges).stddev[0]

    cw, ch = max(8, w // 4), max(8, h // 4)
    corners = []
    for x, y in ((0, 0), (w - cw, 0), (0, h - ch), (w - cw, h - ch)):
        corners.append(ImageStat.Stat(edges.crop((x, y, x + cw, y + ch))).mean[0])
    center = edges.crop((w // 4, h // 4, w * 3 // 4, h * 3 // 4))
    cv = ImageStat.Stat(center).mean[0]
    ratio = (max(corners) + 1e-6) / (cv + 1e-6)
    return round(blur, 2), round(ratio, 2)


def wsrv(url, width=250):
    """通过 wsrv.nl 取图，避开 Wikimedia 的限流。"""
    return ("https://wsrv.nl/?url=" + urllib.parse.quote(url or "", safe="")
            + "&w=%d&output=jpg&q=70" % width)


def analyze_flatness(data):
    """返回 (唯一色比例, 主色占比)。矢量插画前者极低、后者很高。"""
    import io
    from collections import Counter

    from PIL import Image

    im = Image.open(io.BytesIO(data)).convert("RGB")
    im.thumbnail((64, 64))
    px = list(im.getdata())
    n = len(px)
    uniq = len(set(px))
    dom = Counter(px).most_common(1)[0][1]
    return round(uniq / n, 3), round(dom / n, 3)


def scan_mediatype(pause=1.2):
    """用 Commons 的 mediatype 字段判定二维图形（DRAWING/SVG），无需下载图片。

    比逐张下载分析快两个数量级：50 个标题一次请求。
    """
    conn = db()
    rows = conn.execute(
        "SELECT id, title FROM photos WHERE is_graphic IS NULL OR is_graphic = 0"
    ).fetchall()
    conn.close()
    print("待检查 %d 条" % len(rows), flush=True)

    total = flagged = 0
    for i in range(0, len(rows), 50):
        chunk = rows[i:i + 50]
        titles = ["File:" + r["title"] for r in chunk if r["title"]]
        if not titles:
            continue
        params = {
            "action": "query", "format": "json",
            "titles": "|".join(titles),
            "prop": "imageinfo", "iiprop": "mediatype|mime",
        }
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
        try:
            raw = json.loads(http_get(url).decode("utf-8"))
        except Exception as e:
            print("  批次失败: %s" % e, flush=True)
            time.sleep(3)
            continue

        by_title = {}
        for pid, pg in ((raw.get("query") or {}).get("pages") or {}).items():
            ii = (pg.get("imageinfo") or [{}])[0]
            by_title[pg.get("title", "")] = (ii.get("mediatype", ""), ii.get("mime", ""))

        conn = db()
        for r in chunk:
            mt, mime = by_title.get("File:" + r["title"], ("", ""))
            g = 1 if (mt in ("DRAWING", "MULTIMEDIA") or "svg" in mime) else 0
            conn.execute("UPDATE photos SET is_graphic=? WHERE id=?", (g, r["id"]))
            flagged += g
        conn.commit()
        conn.close()
        total += len(chunk)
        if total % 1000 == 0:
            print("  已检查 %d/%d，判定图形 %d" % (total, len(rows), flagged), flush=True)
        time.sleep(pause)

    print("完成：检查 %d 条，判定二维图形 %d 条" % (total, flagged), flush=True)
    return flagged


def scan_graphics(scene=None, limit=None, workers=6):
    """并发检测二维插画：颜色数极少 + 大片纯色 → 判为图形。"""
    import io
    from collections import Counter
    from concurrent.futures import ThreadPoolExecutor

    from PIL import Image

    conn = db()
    sql = "SELECT id, thumb FROM photos WHERE flat IS NULL"
    args = []
    if scene:
        sql += " AND scene=?"
        args.append(scene)
    if limit:
        sql += " LIMIT %d" % int(limit)
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    print("待检测 %d 张（%d 线程）" % (len(rows), workers), flush=True)

    def probe(row):
        try:
            data = http_get(wsrv(row["thumb"], 250), timeout=25)
            im = Image.open(io.BytesIO(data)).convert("RGB")
            im.thumbnail((64, 64))
            px = list(im.getdata())
            uniq = len(set(px)) / len(px)
            dom = Counter(px).most_common(1)[0][1] / len(px)
            return row["id"], round(uniq, 3), round(dom, 3)
        except Exception:
            return row["id"], None, None

    done = flagged = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for pid, uniq, dom in pool.map(probe, rows):
            if uniq is None:
                continue
            g = 1 if uniq < 0.28 else 0
            conn = db()
            conn.execute("UPDATE photos SET flat=?, is_graphic=? WHERE id=?", (uniq, g, pid))
            conn.commit()
            conn.close()
            done += 1
            flagged += g
            if done % 100 == 0:
                print("  已检测 %d/%d，判定图形 %d" % (done, len(rows), flagged), flush=True)

    print("检测完成 %d 张，其中二维图形 %d 张" % (done, flagged), flush=True)
    return done


# ---------------------------------------------------------------------------
# 黑白 / 孤立车辆 / 标识照：图像分析
# ---------------------------------------------------------------------------
_scan_lock = threading.Lock()
_scan_last = [0.0]
_scan_gap = [SCAN_MIN_INTERVAL]


def _pace():
    """全局节流：保证两次请求起始间隔不小于 _scan_gap。"""
    with _scan_lock:
        wait = _scan_last[0] + _scan_gap[0] - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _scan_last[0] = time.monotonic()


def analyze_color(data):
    """黑白判定指标。必须走 RGB——analyze_image 一开始就转 L，颜色信息已丢。"""
    import io
    import math
    from collections import Counter

    from PIL import Image

    im = Image.open(io.BytesIO(data)).convert("RGB")
    im.thumbnail((250, 250))
    small = im.copy()
    small.thumbnail((64, 64))

    rgb = list(small.getdata())
    n = len(rgb)
    if not n:
        return None
    rs = [p[0] for p in rgb]
    gs = [p[1] for p in rgb]
    bs = [p[2] for p in rgb]
    mr, mg, mb = sum(rs) / n, sum(gs) / n, sum(bs) / n

    def corr(a, b, ma, mb):
        sa = math.sqrt(sum((x - ma) ** 2 for x in a) / n)
        sb = math.sqrt(sum((x - mb) ** 2 for x in b) / n)
        if sa < 1e-6 or sb < 1e-6:
            return 1.0
        return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / (n * sa * sb)

    hh, ss, _vv = small.convert("HSV").split()
    H = list(hh.getdata())
    S = list(ss.getdata())
    sat_mean = sum(S) / n
    color_frac = sum(1 for v in S if v >= 50) / n

    bins = Counter()
    for h, v in zip(H, S):
        if v >= 50:
            bins[h * 24 // 256] += 1
    tot = sum(bins.values())
    if tot:
        top = bins.most_common(1)[0][0]
        hue_conc = sum(c for k, c in bins.items() if abs(k - top) <= 1) / tot
        dom_hue = top * 15
    else:
        hue_conc, dom_hue = 0.0, -1

    return {
        "sat_mean": round(sat_mean, 1),
        "color_frac": round(color_frac, 3),
        "hue_conc": round(hue_conc, 2),
        "dom_hue": dom_hue,
        "mono_corr": round(min(corr(rs, gs, mr, mg), corr(rs, bs, mr, mb)), 4),
    }


def analyze_layout(data):
    """孤立主体 / 标识特写的布局特征。"""
    import io
    from collections import Counter

    from PIL import Image, ImageFilter, ImageStat

    im = Image.open(io.BytesIO(data)).convert("RGB")
    im.thumbnail((320, 320))
    w, h = im.size
    if w < 40 or h < 40:
        return None

    edges = im.convert("L").filter(ImageFilter.FIND_EDGES)
    cx0, cy0, cx1, cy1 = w * 2 // 10, h * 2 // 10, w * 8 // 10, h * 8 // 10
    center = ImageStat.Stat(edges.crop((cx0, cy0, cx1, cy1))).mean[0]
    whole = ImageStat.Stat(edges).mean[0]
    center_share = (center + 1e-6) / (whole + 1e-6) / 0.36

    small = im.copy()
    small.thumbnail((64, 64))
    sw, sh = small.size
    px = list(small.getdata())
    ring = []
    for y in range(sh):
        for x in range(sw):
            if x < 4 or y < 4 or x >= sw - 4 or y >= sh - 4:
                q = small.getpixel((x, y))
                ring.append((q[0] >> 3, q[1] >> 3, q[2] >> 3))
    border_dom = Counter(ring).most_common(1)[0][1] / len(ring) if ring else 0
    uniq = len(set(px)) / len(px) if px else 0

    return {
        "center_share": round(center_share, 3),
        "border_dom": round(border_dom, 3),
        "uniq": round(uniq, 3),
    }


def gray_verdict(m):
    """返回 (is_gray, sepia)。四条件缺一不可，单指标极易误判。"""
    if not m:
        return 0, 0
    if m["color_frac"] < GRAY_COLOR_FRAC_MAX and m["sat_mean"] < GRAY_SAT_MAX:
        return 1, 0
    if (m["mono_corr"] >= GRAY_MONO_CORR_MIN
            and m["hue_conc"] >= GRAY_HUE_CONC_MIN
            and GRAY_HUE_LO <= m["dom_hue"] <= GRAY_HUE_HI
            and m["sat_mean"] <= GRAY_SEPIA_SAT_MAX):
        return 1, 1
    return 0, 0


def car_verdict(lay, person):
    if not lay or person:
        return 0.0
    score = 0.0
    if lay["center_share"] >= 1.05:
        score += 35
    if lay["border_dom"] >= 0.40:
        score += 35
    if lay["uniq"] <= 0.45:
        score += 30
    return score


def sign_verdict(lay):
    if not lay:
        return 0
    if (lay["uniq"] <= SIGN_UNIQ_MAX
            and lay["border_dom"] >= SIGN_BORDER_DOM_MIN
            and lay["center_share"] <= 0.90):
        return 1
    return 0


def enrich_scan(limit=None, scene=None, workers=1, only="all"):
    """一次下载同时算黑白、布局、标识三类指标，支持断点续跑。"""
    from concurrent.futures import ThreadPoolExecutor

    conn = db()
    sql = """
      SELECT id, thumb, title, COALESCE(tags,'') AS tags, scene,
             COALESCE(person,0) AS person, COALESCE(is_gray,0) AS is_gray,
             COALESCE(junk_sign,0) AS junk_sign, COALESCE(car_iso,0) AS car_iso,
             CASE
               WHEN lower(COALESCE(tags,'')||' '||COALESCE(title,'')) LIKE '%automobile%'
                 OR lower(COALESCE(tags,'')||' '||COALESCE(title,'')) LIKE '%mobil%'
                 OR lower(COALESCE(tags,'')||' '||COALESCE(title,'')) LIKE '%motor%'
                 OR lower(COALESCE(tags,'')||' '||COALESCE(title,'')) LIKE '%parkir%'
                 OR lower(COALESCE(tags,'')||' '||COALESCE(title,'')) LIKE '%parking%'
                 THEN 0
               WHEN lower(COALESCE(tags,'')||' '||COALESCE(title,'')||' '||COALESCE(descr,''))
                    LIKE '%dutch east indies%'
                 OR lower(COALESCE(tags,'')||' '||COALESCE(title,'')||' '||COALESCE(descr,''))
                    LIKE '%batavia%'
                 OR lower(COALESCE(tags,'')||' '||COALESCE(title,'')||' '||COALESCE(descr,''))
                    LIKE '%kitlv%'
                 OR lower(COALESCE(tags,'')||' '||COALESCE(title,'')||' '||COALESCE(descr,''))
                    LIKE '%tropenmuseum%'
                 OR lower(COALESCE(tags,'')||' '||COALESCE(title,'')||' '||COALESCE(descr,''))
                    LIKE '%colonial%'
                 THEN 1
               WHEN scene IN ('人文','建筑','街景') THEN 2
               ELSE 3 END AS prio
      FROM photos WHERE enrich_at IS NULL
    """
    args = []
    if scene:
        sql += " AND scene=?"
        args.append(scene)
    if only == "car":
        sql += " AND COALESCE(vehicle,0)=1"
    elif only == "sign":
        sql += " AND COALESCE(junk_sign,0)=1"
    sql += " ORDER BY prio, id"
    if limit:
        sql += " LIMIT %d" % int(limit)
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    print("待扫描 %d 张（%d 线程，模式 %s）" % (len(rows), workers, only), flush=True)
    if not rows:
        return 0

    def probe(row):
        url = row["thumb"] or ""
        if not url:
            return row, None, None
        for attempt in ("direct", "wsrv"):
            try:
                _pace()
                if attempt == "direct":
                    if url.lower().endswith((".tiff", ".tif")):
                        raise ValueError("tiff")
                    # retries=1：遇到 429 立刻切备用通道，不在直连上死等
                    data = http_get(thumbify(url, 250), timeout=20, retries=1)
                else:
                    data = http_get(wsrv(url, 250), timeout=30, retries=1)
                m = analyze_color(data)
                lay = analyze_layout(data)
                _scan_gap[0] = max(SCAN_MIN_INTERVAL, _scan_gap[0] * 0.98)
                return row, m, lay
            except Exception:
                _scan_gap[0] = min(2.0, _scan_gap[0] * 1.6)
                continue
        return row, None, None

    done = failed = g_cnt = c_cnt = s_cnt = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for row, m, lay in pool.map(probe, rows):
            if m is None:
                failed += 1
                continue
            g, sep = gray_verdict(m)
            g = max(g, row["is_gray"])
            c = max(car_verdict(lay, row["person"]), row["car_iso"])
            j = max(sign_verdict(lay), row["junk_sign"])
            conn = db()
            conn.execute(
                "UPDATE photos SET sat_mean=?, color_frac=?, hue_conc=?, dom_hue=?, "
                "mono_corr=?, is_gray=?, sepia=MAX(COALESCE(sepia,0),?), car_iso=?, "
                "junk_sign=?, flat=?, enrich_at=? WHERE id=?",
                (m["sat_mean"], m["color_frac"], m["hue_conc"], m["dom_hue"],
                 m["mono_corr"], g, sep, c, j,
                 lay["uniq"] if lay else None, int(time.time()), row["id"]),
            )
            conn.commit()
            conn.close()
            done += 1
            g_cnt += 1 if g else 0
            c_cnt += 1 if c >= CAR_ISO_THRESHOLD else 0
            s_cnt += j
            if done % 100 == 0:
                print("  已扫 %d/%d 黑白 %d 车辆 %d 标识 %d 失败 %d（间隔 %.2fs）"
                      % (done, len(rows), g_cnt, c_cnt, s_cnt, failed, _scan_gap[0]),
                      flush=True)

    set_meta("last_enrich_at", datetime.now().strftime("%Y-%m-%d %H:%M"))
    _facets_cache.clear()
    print("扫描完成 %d 张，失败 %d；黑白 %d，车辆特写 %d，标识 %d"
          % (done, failed, g_cnt, c_cnt, s_cnt), flush=True)
    return done


def recolor():
    """用已存的指标按当前阈值重算黑白/标识判定，不联网。"""
    conn = db()
    rows = conn.execute(
        "SELECT id, sat_mean, color_frac, hue_conc, dom_hue, mono_corr, "
        "car_iso, person FROM photos WHERE sat_mean IS NOT NULL"
    ).fetchall()
    g_n = 0
    for r in rows:
        m = {"sat_mean": r["sat_mean"] or 0, "color_frac": r["color_frac"] or 0,
             "hue_conc": r["hue_conc"] or 0, "dom_hue": r["dom_hue"] if r["dom_hue"] is not None else -1,
             "mono_corr": r["mono_corr"] or 0}
        g, sep = gray_verdict(m)
        conn.execute("UPDATE photos SET is_gray=?, sepia=? WHERE id=?", (g, sep, r["id"]))
        g_n += g
    conn.commit()
    conn.close()
    _facets_cache.clear()
    print("重算 %d 张，黑白 %d" % (len(rows), g_n), flush=True)
    return g_n


def calibrate(kind="gray", n=300):
    """抽样打印指标分布，用于定阈值。"""
    conn = db()
    rows = conn.execute(
        "SELECT id, title, sat_mean, color_frac, hue_conc, dom_hue, mono_corr "
        "FROM photos WHERE sat_mean IS NOT NULL ORDER BY RANDOM() LIMIT %d" % int(n)
    ).fetchall()
    conn.close()
    print("样本 %d 张" % len(rows))
    if kind == "gray":
        rows = sorted(rows, key=lambda r: (r["mono_corr"] or 0), reverse=True)
        print("%-6s %-7s %-7s %-7s %-5s %s" % ("corr", "hue_c", "sat", "cfrac", "hue", "title"))
        for r in rows[:40]:
            print("%-6.3f %-7.2f %-7.1f %-7.3f %-5s %s" % (
                r["mono_corr"] or 0, r["hue_conc"] or 0, r["sat_mean"] or 0,
                r["color_frac"] or 0, r["dom_hue"], (r["title"] or "")[:44]))
    return len(rows)


# ---------------------------------------------------------------------------
# 按 Commons 分类批量判定（走 api.php，不下载图片，比逐张分析快两个数量级）
# ---------------------------------------------------------------------------
CAT_GRAY = ["black and white photographs", "black-and-white photographs",
            "black and white", "sepia", "monochrome photographs", "monochrome"]
CAT_SIGN = ["signs", "signage", "signboards", "street signs", "traffic signs",
            "shop signs", "nameplates", "plaques", "billboards", "road signs",
            "house numbers", "information boards", "notice boards"]
CAT_CAR = ["automobiles", "cars", "vehicles", "motorcycles", "scooters",
           "car parks", "parking lots"]


def scan_categories(pause=0.8):
    """批量查每个文件的 Commons 分类，命中黑白/标识/车辆关键词就打标记。

    零误判（分类是人工维护的），一次请求 50 个文件。
    """
    conn = db()
    rows = conn.execute(
        "SELECT id, title FROM photos WHERE cat_checked IS NULL"
    ).fetchall()
    conn.close()
    print("待查分类 %d 个文件" % len(rows), flush=True)
    if not rows:
        return 0

    total = g_cnt = s_cnt = c_cnt = 0
    for i in range(0, len(rows), 50):
        chunk = rows[i:i + 50]
        titles = ["File:" + r["title"] for r in chunk if r["title"]]
        if not titles:
            continue
        params = {
            "action": "query", "format": "json",
            "titles": "|".join(titles),
            "prop": "categories", "cllimit": "50", "clshow": "!hidden",
        }
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
        try:
            raw = json.loads(http_get(url, timeout=30, retries=2).decode("utf-8"))
        except Exception as e:
            print("  批次失败: %s" % str(e)[:40], flush=True)
            time.sleep(5)
            continue

        by_title = {}
        for _pid, pg in ((raw.get("query") or {}).get("pages") or {}).items():
            cats = " | ".join(c["title"] for c in pg.get("categories", []))
            by_title[pg.get("title", "")] = cats

        conn = db()
        for r in chunk:
            cats = by_title.get("File:" + r["title"], "")
            if not cats:
                continue          # 没拿到分类就不动，留待下次
            cl = cats.lower()
            g = 1 if any(_hit(k, cl) for k in CAT_GRAY) else 0
            j = 1 if any(_hit(k, cl) for k in CAT_SIGN) else 0
            c = 1 if any(_hit(k, cl) for k in CAT_CAR) else 0
            conn.execute(
                "UPDATE photos SET is_gray=MAX(COALESCE(is_gray,0),?), "
                "junk_sign=MAX(COALESCE(junk_sign,0),?), "
                "vehicle=MAX(COALESCE(vehicle,0),?), cats=?, cat_checked=? WHERE id=?",
                (g, j, c, cats, int(time.time()), r["id"]),
            )
            g_cnt += g
            s_cnt += j
            c_cnt += c
        conn.commit()
        conn.close()
        total += len(chunk)
        if total % 1000 == 0:
            print("  已查 %d/%d，黑白 %d 标识 %d 车辆 %d"
                  % (total, len(rows), g_cnt, s_cnt, c_cnt), flush=True)
        time.sleep(pause)

    _facets_cache.clear()
    print("分类查询完成 %d 个，黑白 %d，标识 %d，车辆 %d"
          % (total, g_cnt, s_cnt, c_cnt), flush=True)
    return total


def quality_scan(limit=None, pause=0.35):
    """下载小缩略图计算清晰度与水印风险，支持断点续跑。"""
    conn = db()
    sql = "SELECT id, thumb FROM photos WHERE checked_at IS NULL"
    if limit:
        sql += " LIMIT %d" % int(limit)
    rows = conn.execute(sql).fetchall()
    conn.close()
    print("待检测 %d 张" % len(rows), flush=True)

    done = 0
    for r in rows:
        url = thumbify(r["thumb"] or "", 250)
        if not url:
            continue
        try:
            data = http_get(url, timeout=25)
            blur, ratio = analyze_image(data)
        except Exception:
            time.sleep(1.2)
            continue
        conn = db()
        conn.execute(
            "UPDATE photos SET blur_score=?, corner_score=?, wm_suspect=?, checked_at=? WHERE id=?",
            (blur, ratio, 1 if ratio >= CORNER_RATIO else 0, int(time.time()), r["id"]),
        )
        conn.commit()
        conn.close()
        done += 1
        if done % 50 == 0:
            print("  已检测 %d/%d" % (done, len(rows)), flush=True)
        time.sleep(pause)

    print("检测完成 %d 张" % done, flush=True)
    return done


# 子分类里混着大量元分类（Bali by topic / Books about Bali），跳过
SUB_SKIP = ["by topic", "categories of", "books about", "coats of arms", "maps of",
            "history of", "people of", "unidentified", "media", "files", "wikipedia",
            "gallery", "images", "logos", "diagrams", "charts", "documents", "texts",
            "videos", "audio", "in popular culture", "stamps", "coins", "postcards",
            "banners", "screenshots", "svg"]


def _useful_subcat(name):
    n = name.lower()
    return not any(k in n for k in SUB_SKIP)


def expand_deep(sub_limit=6, files_per=100, pages=5, pause=2.5):
    """深度扩充：主分类翻页 + 进入子分类，量级比单页抓取大一个数量级。"""
    total = 0
    started = time.time()

    for i, (cat, country) in enumerate(CATEGORIES, 1):
        subs = [s for s in list_subcats(cat, sub_limit * 3) if _useful_subcat(s)][:sub_limit]
        time.sleep(pause)

        got = 0
        # 主分类翻页
        cont = None
        for _ in range(pages):
            items, cont = wikimedia_category(cat, files_per, cont)
            for it in items:
                if upsert_photo(it, country, cat):
                    got += 1
            if not cont:
                break
            time.sleep(pause)

        # 子分类各取一页
        for s in subs:
            items, _ = wikimedia_category(s, files_per)
            for it in items:
                if upsert_photo(it, country, s):
                    got += 1
            time.sleep(pause)

        total += got
        print("[%02d/%d] %-34s 子类%2d 新增%4d 累计%6d"
              % (i, len(CATEGORIES), cat, len(subs), got, total), flush=True)

    set_meta("last_expand_at", datetime.now().strftime("%Y-%m-%d %H:%M"))
    set_meta("last_expand_added", str(total))
    print("深度扩充完成 +%d，用时 %ds" % (total, time.time() - started), flush=True)
    return total


# ----------------------------------------------------------------------------
# 生活场景采集：真实日常，而不是地标风景
# ----------------------------------------------------------------------------

LIFE_SEEDS = [
    # ---- 印尼 · 吃喝日常 ----
    ("warung makan", "印度尼西亚"), ("warung kopi", "印度尼西亚"),
    ("warung tenda", "印度尼西亚"), ("angkringan", "印度尼西亚"),
    ("kaki lima", "印度尼西亚"), ("pedagang kaki lima", "印度尼西亚"),
    ("pedagang sayur", "印度尼西亚"), ("gerobak", "印度尼西亚"),
    ("nasi campur", "印度尼西亚"), ("nasi padang", "印度尼西亚"),
    ("bakso", "印度尼西亚"), ("mie ayam", "印度尼西亚"), ("soto", "印度尼西亚"),
    ("es teh", "印度尼西亚"), ("kopi tubruk", "印度尼西亚"),
    ("rumah makan", "印度尼西亚"), ("kantin", "印度尼西亚"),
    ("pasar tradisional", "印度尼西亚"), ("pasar pagi", "印度尼西亚"),
    ("pasar malam", "印度尼西亚"), ("pasar ikan", "印度尼西亚"),
    ("pasar sayur", "印度尼西亚"),

    # ---- 印尼 · 街巷与生活 ----
    ("kampung", "印度尼西亚"), ("gang", "印度尼西亚"),
    ("ojek", "印度尼西亚"), ("angkot", "印度尼西亚"),
    ("terminal bus", "印度尼西亚"), ("stasiun", "印度尼西亚"),
    ("tukang", "印度尼西亚"), ("bengkel", "印度尼西亚"),
    ("rumah warga", "印度尼西亚"), ("sekolah dasar", "印度尼西亚"),
    ("anak sekolah", "印度尼西亚"), ("masjid kampung", "印度尼西亚"),
    ("upacara adat", "印度尼西亚"), ("batik", "印度尼西亚"),
    ("pos ronda", "印度尼西亚"), ("lapak", "印度尼西亚"),

    # ---- 新加坡 · 吃喝日常 ----
    ("kopitiam", "新加坡"), ("hawker stall", "新加坡"),
    ("teh tarik", "新加坡"), ("kaya toast", "新加坡"),
    ("economy rice", "新加坡"), ("cai fan", "新加坡"),
    ("wet market singapore", "新加坡"), ("coffee shop singapore", "新加坡"),
    ("food court singapore", "新加坡"), ("hawker food", "新加坡"),

    # ---- 新加坡 · 街区日常 ----
    ("void deck", "新加坡"), ("HDB corridor", "新加坡"),
    ("heartland singapore", "新加坡"), ("neighbourhood singapore", "新加坡"),
    ("tiong bahru", "新加坡"), ("bedok", "新加坡"),
    ("ang mo kio", "新加坡"), ("yishun", "新加坡"),
    ("toa payoh", "新加坡"), ("redhill singapore", "新加坡"),
    ("commonwealth singapore", "新加坡"), ("pasir panjang", "新加坡"),
    ("jurong west", "新加坡"), ("woodlands singapore", "新加坡"),
]

LIFE_CATEGORIES = [
    ("Category:Warungs", "印度尼西亚"),
    ("Category:Street food in Indonesia", "印度尼西亚"),
    ("Category:Traditional markets in Indonesia", "印度尼西亚"),
    ("Category:Villages in Bali", "印度尼西亚"),
    ("Category:Houses in Indonesia", "印度尼西亚"),
    ("Category:People of Indonesia", "印度尼西亚"),
    ("Category:Children of Indonesia", "印度尼西亚"),
    ("Category:Batik", "印度尼西亚"),
    ("Category:Void decks in Singapore", "新加坡"),
    ("Category:People of Singapore", "新加坡"),
    ("Category:Food courts in Singapore", "新加坡"),
    ("Category:HDB flats", "新加坡"),
]


# 第二批：更细的生活颗粒度（摊贩、店铺、出行、社区活动、农渔）
LIFE_SEEDS_2 = [
    # ---- 印尼 · 店铺与摊贩 ----
    ("warung tegal", "印度尼西亚"), ("warteg", "印度尼西亚"),
    ("warung nasi", "印度尼西亚"), ("warung sembako", "印度尼西亚"),
    ("toko kelontong", "印度尼西亚"), ("sembako", "印度尼西亚"),
    ("jual gorengan", "印度尼西亚"), ("gorengan", "印度尼西亚"),
    ("pedagang asongan", "印度尼西亚"), ("pedagang buah", "印度尼西亚"),
    ("pedagang ikan", "印度尼西亚"), ("tukang parkir", "印度尼西亚"),
    ("kedai kopi", "印度尼西亚"), ("kedai makan", "印度尼西亚"),
    ("pangkas rambut indonesia", "印度尼西亚"), ("tukang jahit", "印度尼西亚"),
    ("laundry kiloan", "印度尼西亚"), ("warnet", "印度尼西亚"),
    ("konter pulsa", "印度尼西亚"), ("apotek", "印度尼西亚"),
    ("toko emas", "印度尼西亚"),

    # ---- 印尼 · 市场变体 ----
    ("pasar kaget", "印度尼西亚"), ("pasar subuh", "印度尼西亚"),
    ("pasar loak", "印度尼西亚"), ("pasar buah", "印度尼西亚"),
    ("pasar bunga", "印度尼西亚"), ("pasar hewan", "印度尼西亚"),
    ("tempat pelelangan ikan", "印度尼西亚"),

    # ---- 印尼 · 出行 ----
    ("becak", "印度尼西亚"), ("delman", "印度尼西亚"), ("bajaj", "印度尼西亚"),
    ("commuter line", "印度尼西亚"), ("halte bus", "印度尼西亚"),
    ("pangkalan ojek", "印度尼西亚"), ("cuci motor", "印度尼西亚"),
    ("tukang becak", "印度尼西亚"),

    # ---- 印尼 · 社区与仪式 ----
    ("pos kamling", "印度尼西亚"), ("balai desa", "印度尼西亚"),
    ("gapura", "印度尼西亚"), ("kerja bakti", "印度尼西亚"),
    ("gotong royong", "印度尼西亚"), ("arisan", "印度尼西亚"),
    ("pengajian", "印度尼西亚"), ("kenduri", "印度尼西亚"),
    ("hajatan", "印度尼西亚"), ("posyandu", "印度尼西亚"),
    ("puskesmas", "印度尼西亚"),

    # ---- 印尼 · 日常起居与农渔 ----
    ("dapur rumah", "印度尼西亚"), ("ibu masak", "印度尼西亚"),
    ("sumur", "印度尼西亚"), ("lapangan bola", "印度尼西亚"),
    ("bulu tangkis", "印度尼西亚"), ("layang-layang", "印度尼西亚"),
    ("sawah", "印度尼西亚"), ("ladang", "印度尼西亚"),
    ("kebun", "印度尼西亚"), ("ternak", "印度尼西亚"),
    ("kandang", "印度尼西亚"), ("nelayan", "印度尼西亚"),
    ("perahu", "印度尼西亚"), ("dermaga", "印度尼西亚"),
    ("tambak", "印度尼西亚"), ("petani", "印度尼西亚"),
    ("panen", "印度尼西亚"),

    # ---- 新加坡 · 熟食与店铺 ----
    ("mama shop", "新加坡"), ("provision shop", "新加坡"),
    ("sundry shop", "新加坡"), ("zi char singapore", "新加坡"),
    ("bak kut teh", "新加坡"), ("laksa", "新加坡"),
    ("char kway teow", "新加坡"), ("hokkien mee", "新加坡"),
    ("nasi lemak", "新加坡"), ("roti prata", "新加坡"),
    ("murtabak", "新加坡"), ("kueh", "新加坡"),
    ("pasar malam singapore", "新加坡"),
    ("wet market stall", "新加坡"), ("hawker centre table", "新加坡"),

    # ---- 新加坡 · 组屋生活 ----
    ("HDB block", "新加坡"), ("lift lobby", "新加坡"),
    ("common corridor", "新加坡"), ("playground singapore", "新加坡"),
    ("neighbourhood park", "新加坡"), ("community garden singapore", "新加坡"),

    # ---- 新加坡 · 具体市镇 ----
    ("Tekka Centre", "新加坡"), ("Geylang Serai", "新加坡"),
    ("Old Airport Road", "新加坡"), ("Changi Village", "新加坡"),
    ("Tanglin Halt", "新加坡"), ("Ghim Moh", "新加坡"),
    ("Whampoa", "新加坡"), ("Balestier Market", "新加坡"),
    ("Queenstown", "新加坡"), ("Marine Parade", "新加坡"),
    ("Clementi", "新加坡"), ("Hougang", "新加坡"),
    ("Serangoon", "新加坡"), ("Kallang", "新加坡"),
    ("Jalan Besar", "新加坡"), ("Zion Road", "新加坡"),
    ("Alexandra", "新加坡"), ("Dakota", "新加坡"),
    ("Siglap", "新加坡"), ("Telok Kurau", "新加坡"),
    ("Paya Lebar", "新加坡"), ("Eunos", "新加坡"),
    ("Pasir Ris", "新加坡"), ("Sembawang", "新加坡"),
    ("Kranji", "新加坡"), ("Lim Chu Kang", "新加坡"),
    ("Sungei Buloh", "新加坡"), ("Pulau Ubin village", "新加坡"),
]

LIFE_CATEGORIES_2 = [
    ("Category:Street vendors in Indonesia", "印度尼西亚"),
    ("Category:Food stalls in Indonesia", "印度尼西亚"),
    ("Category:Rice fields in Indonesia", "印度尼西亚"),
    ("Category:Fishing in Indonesia", "印度尼西亚"),
    ("Category:Becak", "印度尼西亚"),
    ("Category:Public transport in Indonesia", "印度尼西亚"),
    ("Category:Rural areas of Indonesia", "印度尼西亚"),
    ("Category:Wet markets in Singapore", "新加坡"),
    ("Category:Playgrounds in Singapore", "新加坡"),
    ("Category:Community centres in Singapore", "新加坡"),
]


def ingest_life(limit=40, batch=1, pause=1.8):
    """按生活场景关键词采集：街边摊、菜市场、小巷、组屋走廊这类真实日常。"""
    seeds = LIFE_SEEDS if batch == 1 else LIFE_SEEDS_2
    cats = LIFE_CATEGORIES if batch == 1 else LIFE_CATEGORIES_2
    total = 0
    started = time.time()

    for i, (q, country) in enumerate(seeds, 1):
        n = ingest_query(q, country, limit=limit)
        total += n
        if n:
            print("[%02d/%d] %-28s +%d" % (i, len(seeds), q, n), flush=True)
        time.sleep(pause)

    for cat, country in cats:
        items, _ = wikimedia_category(cat, 100)
        n = 0
        for it in items:
            if upsert_photo(it, country, cat):
                n += 1
        total += n
        print("[分类] %-38s +%d" % (cat, n), flush=True)
        time.sleep(pause)

    set_meta("last_life_at", datetime.now().strftime("%Y-%m-%d %H:%M"))
    set_meta("last_life_added", str(total))
    print("生活场景采集完成(第%d批) +%d，用时 %ds" % (batch, total, time.time() - started),
          flush=True)
    return total


def purge_life_noise():
    """清理生活词采集里跑题的素材：标题和描述完全没有印尼/新加坡信号的一律删除。

    生活词（如 warung kopi、becak）在 Commons 上会捞回欧洲、南亚的同名场景，
    这些照片标题往往只写地名或人名，没有任何本地语言特征。
    """
    life_tags = ({q for q, _ in LIFE_SEEDS} | {q for q, _ in LIFE_SEEDS_2}
                 | {q for q, _ in DEVICE_SEEDS})
    conn = db()
    rows = conn.execute("SELECT id, title, descr, tags FROM photos").fetchall()
    killed = 0
    for r in rows:
        if r["tags"] not in life_tags:
            continue
        blob = " ".join([r["title"] or "", r["descr"] or ""])
        if not has_region_signal(blob):
            conn.execute("DELETE FROM photos WHERE id=?", (r["id"],))
            killed += 1
    conn.commit()
    left = conn.execute("SELECT COUNT(*) c FROM photos").fetchone()["c"]
    conn.close()
    print("生活词清理 %d 条，剩余 %d 条" % (killed, left), flush=True)
    return killed


# 第三批：数码设备与汽车的使用场景
# 经验：印尼语具体短语能命中（parkir mobil、ojol），缩写和英文泛词会跑题
# （SPBU 命中圣彼得堡大学、warnet 命中墨西哥网吧），所以下面只留验证过有效的词
DEVICE_SEEDS = [
    # ---- 印尼 · 手机 ----
    ("konter hp", "印度尼西亚"), ("toko hp", "印度尼西亚"),
    ("gerai ponsel", "印度尼西亚"), ("servis hp", "印度尼西亚"),
    ("kartu perdana", "印度尼西亚"), ("isi pulsa", "印度尼西亚"),
    ("main hp", "印度尼西亚"), ("pakai hp", "印度尼西亚"),

    # ---- 印尼 · 电脑与办公 ----
    ("toko komputer", "印度尼西亚"), ("meja kerja", "印度尼西亚"),
    ("kantor desa", "印度尼西亚"), ("laptop indonesia", "印度尼西亚"),

    # ---- 印尼 · 汽车与摩托 ----
    ("parkir mobil", "印度尼西亚"), ("tempat parkir", "印度尼西亚"),
    ("parkiran motor", "印度尼西亚"), ("cuci mobil", "印度尼西亚"),
    ("bengkel mobil", "印度尼西亚"), ("dealer mobil", "印度尼西亚"),
    ("showroom mobil", "印度尼西亚"), ("toyota avanza", "印度尼西亚"),
    ("honda beat", "印度尼西亚"), ("honda vario", "印度尼西亚"),
    ("yamaha nmax", "印度尼西亚"), ("ojol", "印度尼西亚"),
    ("driver ojol", "印度尼西亚"), ("kurir paket", "印度尼西亚"),
    ("jalan tol", "印度尼西亚"), ("lalu lintas", "印度尼西亚"),
    ("jembatan layang", "印度尼西亚"), ("terminal bus", "印度尼西亚"),

    # ---- 新加坡 ----
    ("Sim Lim Square", "新加坡"), ("Funan mall", "新加坡"),
    ("Challenger singapore", "新加坡"), ("Singtel shop", "新加坡"),
    ("car park singapore", "新加坡"), ("petrol station singapore", "新加坡"),
    ("expressway singapore", "新加坡"), ("car showroom singapore", "新加坡"),
]

DEVICE_CATEGORIES = [
    ("Category:Motorcycles in Indonesia", "印度尼西亚"),
    ("Category:Roads in Indonesia", "印度尼西亚"),
    ("Category:Petrol stations in Indonesia", "印度尼西亚"),
    ("Category:Automobiles of Indonesia", "印度尼西亚"),
    ("Category:Roads in Singapore", "新加坡"),
    ("Category:Car parks in Singapore", "新加坡"),
    ("Category:Automobiles of Singapore", "新加坡"),
]


def ingest_device(limit=40, pause=1.8):
    """采集数码设备与汽车的使用场景：手机店、网吧、加油站、4S 店、街头车流。"""
    total = 0
    started = time.time()

    for i, (q, country) in enumerate(DEVICE_SEEDS, 1):
        n = ingest_query(q, country, limit=limit)
        total += n
        if n:
            print("[%02d/%d] %-30s +%d" % (i, len(DEVICE_SEEDS), q, n), flush=True)
        time.sleep(pause)

    for cat, country in DEVICE_CATEGORIES:
        items, _ = wikimedia_category(cat, 100)
        n = 0
        for it in items:
            if upsert_photo(it, country, cat):
                n += 1
        total += n
        print("[分类] %-38s +%d" % (cat, n), flush=True)
        time.sleep(pause)

    set_meta("last_device_at", datetime.now().strftime("%Y-%m-%d %H:%M"))
    set_meta("last_device_added", str(total))
    print("数码汽车采集完成 +%d，用时 %ds" % (total, time.time() - started), flush=True)
    return total


def ensure_local(query):
    """本地结果太少时，实时补采一次（带冷却，避免刷接口）。"""
    now = time.time()
    if _recent_queries.get(query, 0) > now - 300:
        return 0
    _recent_queries[query] = now
    with _ingest_lock:
        return ingest_query(query, None, limit=40)


# ----------------------------------------------------------------------------
# 检索
# ----------------------------------------------------------------------------

STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "in", "on", "at", "to", "by", "for", "with",
    "cc", "sa", "by-sa", "jpg", "jpeg", "png", "photo", "image", "file", "picture",
    "stock", "素材", "图片",
}


def tokenize(q):
    raw = re.split(r"[\s,，、/|]+", (q or "").lower().strip())
    out = []
    for t in raw:
        t = t.strip("()[]\"'.-_")
        if not t or t in STOPWORDS:
            continue
        if has_chinese(t):
            out.extend(segment_cn(t))
            continue
        if re.fullmatch(r"[a-z0-9]+", t) and len(t) < 2:
            continue
        out.append(t)
    return out


# 中文查询词 → 英文同义词（库里标题基本是英文，不映射就搜不到）
CN2EN = {
    "海滩": ["beach", "coast", "shore"], "沙滩": ["beach", "sand"],
    "海边": ["beach", "seaside", "coast"], "日落": ["sunset"],
    "日出": ["sunrise"], "稻田": ["rice terrace", "rice field", "paddy"],
    "梯田": ["rice terrace", "terrace"], "火山": ["volcano", "mountain"],
    "瀑布": ["waterfall"], "森林": ["forest", "jungle"],
    "湖泊": ["lake"], "公园": ["park", "garden"],
    "寺庙": ["temple", "shrine"], "清真寺": ["mosque"],
    "教堂": ["church", "cathedral"], "建筑": ["architecture", "building"],
    "天际线": ["skyline"], "街景": ["street", "alley"],
    "街道": ["street"], "市场": ["market", "bazaar"],
    "夜市": ["night market", "market"], "美食": ["food", "dish", "cuisine"],
    "小吃": ["snack", "street food"], "餐厅": ["restaurant", "eatery"],
    "咖啡馆": ["cafe", "coffee", "kopi"], "咖啡": ["coffee", "cafe", "kopi"],
    "酒吧": ["bar", "pub"], "酒店": ["hotel"], "度假村": ["resort"],
    "民宿": ["guesthouse", "homestay", "villa"], "泳池": ["pool"],
    "地铁": ["mrt", "metro", "subway"], "公交": ["bus"], "机场": ["airport"],
    "火车站": ["station", "railway"], "港口": ["harbour", "harbor", "port"],
    "船": ["boat", "ferry"], "摩托车": ["scooter", "motorbike"],
    "人": ["people", "person"], "人群": ["crowd", "people"],
    "舞蹈": ["dance", "dancer"], "节庆": ["festival", "ceremony"],
    "仪式": ["ceremony", "ritual"], "夜市小吃": ["street food"],
    "早餐": ["breakfast"], "午餐": ["lunch"], "晚餐": ["dinner"],
    "聚餐": ["dining", "gathering", "meal"], "用餐": ["dining", "restaurant"],
    "夜景": ["night", "nighttime"], "日落海滩": ["sunset", "beach"],
    "购物": ["shopping", "mall"], "商场": ["mall", "shopping"],
    "植物园": ["botanic garden", "garden"], "动物园": ["zoo"],
    "海滩日落": ["sunset", "beach"],
    # 生活场景补充
    "小摊": ["warung", "stall", "vendor"], "摊子": ["stall", "vendor"],
    "摊位": ["stall", "stand", "lapak"], "摊贩": ["vendor", "hawker", "pedagang"],
    "路边摊": ["street vendor", "stall", "warung"], "大排档": ["hawker", "stall", "eatery"],
    "吃饭": ["eating", "dining", "meal", "makan"], "饭馆": ["restaurant", "eatery", "warung"],
    "食堂": ["canteen", "kantin"], "菜市场": ["wet market", "market", "pasar"],
    "早市": ["morning market", "pasar pagi"], "夜市摊": ["night market", "pasar malam"],
    "水果摊": ["fruit stall", "fruit market"], "鱼市": ["fish market", "pasar ikan"],
    "组屋": ["hdb", "public housing", "flat", "block"], "走廊": ["corridor", "hallway"],
    "电梯": ["lift", "elevator"], "楼下": ["void deck", "ground floor"],
    "理发": ["barber", "barbershop", "haircut"], "理发店": ["barbershop", "barber"],
    "洗衣店": ["laundry"], "药店": ["pharmacy", "apotek"], "杂货店": ["grocery", "sundry", "provision"],
    "便利店": ["convenience store", "minimart"], "小卖部": ["shop", "store", "kiosk"],
    "网吧": ["internet cafe", "warnet"], "修车": ["workshop", "garage", "bengkel"],
    "摩托车": ["motorcycle", "scooter", "motorbike"], "三轮车": ["rickshaw", "becak", "trishaw"],
    "小巴": ["minibus", "van", "angkot"], "马车": ["carriage", "cart"],
    "渔船": ["fishing boat", "boat"], "渔村": ["fishing village", "village"],
    "农田": ["farm", "field", "paddy"], "菜地": ["garden", "vegetable plot"],
    "收割": ["harvest"], "养牛": ["cattle", "livestock"],
    "婚礼": ["wedding"], "宴席": ["banquet", "feast", "kenduri"],
    "仪式": ["ceremony", "ritual"], "祈祷": ["prayer", "praying"],
    "小学": ["primary school", "school"], "学生": ["student", "schoolchildren"],
    "孩子": ["children", "kids"], "老人": ["elderly", "old man", "old woman"],
    "菜饭": ["economy rice", "cai fan", "mixed rice"], "杂菜饭": ["nasi campur", "economy rice"],
    "糕点": ["kueh", "cake", "pastry"], "吐司": ["toast", "bread"],
    "奶茶": ["teh tarik", "milk tea"], "咖啡店": ["kopitiam", "coffee shop", "cafe"],
    # 数码 / 汽车 / 出行
    "汽车": ["car", "automobile", "vehicle"], "轿车": ["car", "sedan"],
    "停车场": ["parking", "car park", "parkir"], "加油站": ["petrol station", "gas station"],
    "手机": ["smartphone", "mobile phone", "handphone", "ponsel", "hp"],
    "电脑": ["computer", "laptop", "komputer"], "笔记本": ["laptop", "notebook"],
    "电动车": ["electric vehicle", "electric car", "scooter"],
    "公交站": ["bus stop", "bus station", "terminal"], "码头": ["pier", "jetty", "dermaga"],
    "高速": ["highway", "expressway", "toll road"], "天桥": ["overpass", "flyover", "bridge"],
    "红绿灯": ["traffic light"], "马路": ["road", "street"], "人行道": ["sidewalk", "pavement"],
    "开车": ["driving", "driver"], "骑车": ["cycling", "riding", "motorcycle"],
    "送货": ["delivery", "courier"], "快递": ["parcel", "courier", "delivery"],
    # 店铺 / 商业
    "商店": ["shop", "store"], "超市": ["supermarket", "grocery"],
    "菜摊": ["vegetable stall", "market stall"], "蔬菜": ["vegetable"],
    "海鲜": ["seafood", "fish"], "饮料": ["drink", "beverage"],
    "收银": ["cashier", "checkout"], "店员": ["shop assistant", "staff", "clerk"],
    "老板": ["owner", "shopkeeper"], "顾客": ["customer"],
    "货架": ["shelf", "shelves"], "商品": ["goods", "product", "merchandise"],
    "招牌": ["sign", "signboard"], "价格": ["price", "pricing"],
    "排队": ["queue", "line"], "付款": ["payment", "paying", "checkout"],
    "扫码": ["qr code", "scanning"], "现金": ["cash", "money"],
    # 动作 / 人物
    "聊天": ["chatting", "talking"], "工作": ["working", "work"],
    "办公": ["office", "working"], "学习": ["studying", "study", "learning"],
    "做饭": ["cooking", "cook"], "吃饭的": ["eating", "dining"],
    "家庭": ["family"], "朋友": ["friends"], "年轻人": ["young people", "youth"],
    "上班": ["commuting", "going to work"], "通勤": ["commute", "commuter"],
    "走路": ["walking", "pedestrian"], "笑": ["smiling", "laughing"],
    # 空间
    "厨房": ["kitchen"], "客厅": ["living room"], "卧室": ["bedroom"],
    "阳台": ["balcony"], "楼梯": ["stairs", "staircase"], "屋顶": ["roof"],
    "货仓": ["warehouse", "storage"], "工地": ["construction site", "construction"],
}

# 中文分词词表：查询词、城市名、场景名、常用补充词
CN_EXTRA = [
    "巴厘岛", "雅加达", "日惹", "万隆", "泗水", "棉兰", "龙目岛", "科莫多", "四王群岛",
    "新加坡", "印尼", "印度尼西亚", "乌布", "水明漾", "库塔", "沙努尔", "金巴兰",
    "努沙杜瓦", "佩尼达", "乌鲁瓦图", "海神庙", "长谷", "登巴萨",
    "牛车水", "小印度", "滨海湾", "圣淘沙", "乌节路", "克拉码头", "甘榜格南",
    "组屋", "走廊", "小摊", "摊位", "摊贩", "吃饭", "用餐", "聚餐",
    "照片", "图片", "素材", "场景", "背景", "特写", "远景", "近景",
]

CN_VOCAB = sorted(
    {w for w in (
        set(CN2EN) | set(CN_EXTRA)
        | {name for _, name, _ in CITIES}
        | {name for name, _ in SCENES}
    ) if len(w) >= 2},
    key=len, reverse=True,
)

CN_STOP = {"的", "了", "和", "与", "在", "有", "是", "我", "要", "找", "张", "个",
           "些", "一", "点", "很", "都", "也", "就", "还", "被", "把", "给"}


def has_chinese(text):
    return any("\u4e00" <= ch <= "\u9fff" for ch in (text or ""))


def segment_cn(text):
    """最长匹配切分中文。认不出的整串保留，避免拆成单字造成误命中。"""
    out, i, n = [], 0, len(text)
    while i < n:
        for w in CN_VOCAB:
            if text.startswith(w, i):
                out.append(w)
                i += len(w)
                break
        else:
            i += 1
    return out if out else [text]

_TOKEN_CACHE = {}


def expand_token(t):
    """把查询词展开成同义词组，中文词自动带上英文对应词。"""
    if t in _TOKEN_CACHE:
        return _TOKEN_CACHE[t]
    variants = [t] + [v for v in CN2EN.get(t, []) if v != t]
    _TOKEN_CACHE[t] = variants
    return variants


def search_photos(q, country="", city="", scene="", orient="", only_saved=False,
                  page=1, per=24, min_pixels=0, hide_blur=False, hide_wm=False,
                  hide_selfie=False, hide_solo=False, hide_dated=False,
                  hide_people=False, hide_graphic=False,
                  hide_gray=False, hide_car=False, hide_junk=False):
    """精确优先的检索：全部关键词命中才算精确匹配；否则降级为弱匹配并显式标注。"""
    conn = db()
    where, args = ["hidden=0"], []
    if country:
        where.append("country=?")
        args.append(country)
    if city:
        where.append("city=?")
        args.append(city)
    if scene:
        where.append("scene=?")
        args.append(scene)
    if orient:
        where.append("orientation=?")
        args.append(orient)
    if only_saved:
        where.append("saved=1")
    if hide_selfie:
        where.append("COALESCE(selfie,0)=0")
    if hide_solo:
        where.append("COALESCE(solo,0)=0")
    if hide_dated:
        where.append("COALESCE(dated,0)=0")
    if hide_people:
        where.append("COALESCE(person,0)=0")
    if hide_wm:
        where.append("COALESCE(wm_suspect,0)=0")
    if hide_graphic:
        where.append("COALESCE(is_graphic,0)=0")
    if hide_gray:
        where.append("COALESCE(is_gray,0)=0")
    if hide_car:
        where.append("COALESCE(car_iso,0) < ?")
        args.append(CAR_ISO_THRESHOLD)
    if hide_junk:
        where.append("COALESCE(junk_sign,0)=0")
    if hide_blur:
        where.append("(blur_score IS NULL OR blur_score >= ?)")
        args.append(BLUR_THRESHOLD)
    if min_pixels:
        # 尺寸未知的来源（如 Flickr）不参与分辨率过滤，否则会被全部误杀
        where.append("(width = 0 OR height = 0 OR (width * height) >= ?)")
        args.append(min_pixels)

    sql = "SELECT * FROM photos WHERE " + " AND ".join(where)
    rows = conn.execute(sql, args).fetchall()
    conn.close()

    toks = tokenize(q)
    mode = "browse"
    exact_total = loose_total = 0
    ranked = []  # [(row, match_pct, weak)]

    if toks:
        max_score = 3.0 * len(toks)
        exact, loose = [], []
        for r in rows:
            st = r["search_text"] or ""
            title = (r["title"] or "").lower()
            fields = " ".join([
                r["country"] or "", r["city"] or "", r["scene"] or ""
            ]).lower()
            hit = []
            for t in toks:
                vs = expand_token(t)
                if any(v in st for v in vs):
                    hit.append((t, vs))
            if not hit:
                continue
            score = 0
            for _, vs in hit:
                score += 3 if any(v in title or v in fields for v in vs) else 1
            pct = int(round(min(1.0, score / max_score) * 100))
            if len(hit) == len(toks):
                exact.append((score, r["saved"], r["id"], r, pct))
            else:
                loose.append((len(hit), score, r["saved"], r["id"], r, pct))

        if exact:
            mode = "exact"
            exact.sort(key=lambda x: (-x[0], -x[1], -x[2]))
            ranked = [(x[3], x[4], False) for x in exact]
            exact_total, loose_total = len(exact), len(loose)
        elif loose:
            loose.sort(key=lambda x: (-x[0], -x[1], -x[2], -x[3]))
            ranked = [(x[4], x[5], True) for x in loose]
            mode = "loose"
            exact_total, loose_total = 0, len(loose)
        else:
            mode = "none"
    else:
        ordered = sorted(rows, key=lambda r: (r["saved"], r["id"]), reverse=True)
        ranked = [(r, 100, False) for r in ordered]
        exact_total = len(ordered)

    total = len(ranked)
    start = (page - 1) * per
    items = []
    for r, pct, weak in ranked[start:start + per]:
        d = dict(r)
        d.pop("search_text", None)
        d["match"] = pct
        d["weak"] = weak
        items.append(d)

    return {
        "total": total,
        "exact_total": exact_total,
        "loose_total": loose_total,
        "mode": mode,
        "tokens": toks,
        "page": page,
        "per": per,
        "items": items,
    }


def facets(country=""):
    now = time.time()
    hit = _facets_cache.get(country)
    if hit and now - hit[0] < 20:
        return hit[1]

    conn = db()
    where, args = ["hidden=0"], []
    if country:
        where.append("country=?")
        args.append(country)
    w = " WHERE " + " AND ".join(where)

    cities = conn.execute(
        "SELECT city, COUNT(*) c FROM photos%s GROUP BY city ORDER BY c DESC" % w, args
    ).fetchall()
    scenes = conn.execute(
        "SELECT scene, COUNT(*) c FROM photos%s GROUP BY scene ORDER BY c DESC" % w, args
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) c FROM photos WHERE hidden=0").fetchone()["c"]
    saved = conn.execute(
        "SELECT COUNT(*) c FROM photos WHERE saved=1 AND hidden=0").fetchone()["c"]
    by_country = conn.execute(
        "SELECT country, COUNT(*) c FROM photos WHERE hidden=0 GROUP BY country ORDER BY c DESC"
    ).fetchall()

    q = {
        "lowres": conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE hidden=0 AND width*height < ?",
            (MIN_PIXELS,)).fetchone()["c"],
        "blurry": conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE hidden=0 AND blur_score IS NOT NULL "
            "AND blur_score < ?", (BLUR_THRESHOLD,)).fetchone()["c"],
        "wm": conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE hidden=0 AND COALESCE(wm_suspect,0)=1"
        ).fetchone()["c"],
        "people": conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE hidden=0 AND COALESCE(person,0)=1"
        ).fetchone()["c"],
        "solo": conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE hidden=0 AND COALESCE(solo,0)=1"
        ).fetchone()["c"],
        "selfie": conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE hidden=0 AND COALESCE(selfie,0)=1"
        ).fetchone()["c"],
        "dated": conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE hidden=0 AND COALESCE(dated,0)=1"
        ).fetchone()["c"],
        "graphic": conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE hidden=0 AND COALESCE(is_graphic,0)=1"
        ).fetchone()["c"],
        "gray": conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE hidden=0 AND COALESCE(is_gray,0)=1"
        ).fetchone()["c"],
        "sepia": conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE hidden=0 AND COALESCE(sepia,0)=1"
        ).fetchone()["c"],
        "car": conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE hidden=0 AND COALESCE(car_iso,0) >= ?",
            (CAR_ISO_THRESHOLD,)).fetchone()["c"],
        "junk": conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE hidden=0 AND COALESCE(junk_sign,0)=1"
        ).fetchone()["c"],
        "scanned": conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE enrich_at IS NOT NULL AND enrich_at > 0"
        ).fetchone()["c"],
        "checked": conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE checked_at IS NOT NULL").fetchone()["c"],
    }
    conn.close()

    result = {
        "total": total,
        "saved": saved,
        "last_update_at": get_meta("last_update_at", ""),
        "last_update_added": get_meta("last_update_added", ""),
        "quality": q,
        "min_pixels": MIN_PIXELS,
        "cities": [{"name": r["city"], "count": r["c"]} for r in cities],
        "scenes": [{"name": r["scene"], "count": r["c"]} for r in scenes],
        "countries": [{"name": r["country"], "count": r["c"]} for r in by_country],
    }
    _facets_cache[country] = (now, result)
    return result

# ----------------------------------------------------------------------------
# 图片缓存代理
# ----------------------------------------------------------------------------

def sniff_type(b):
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "application/octet-stream"


def fetch_image(url):
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()
    path = os.path.join(CACHE, key + ".bin")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read(), sniff_type(open(path, "rb").read(16))
    data = http_get(url, timeout=30)
    with open(path, "wb") as f:
        f.write(data)
    return data, sniff_type(data)


# ----------------------------------------------------------------------------
# HTTP 服务
# ----------------------------------------------------------------------------

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        def one(k, d=""):
            return (qs.get(k) or [d])[0]

        try:
            if path == "/" or path == "/index.html":
                return self._file(os.path.join(WEB, "index.html"), CONTENT_TYPES[".html"])

            if path.startswith("/static/"):
                name = os.path.basename(path)
                ext = os.path.splitext(name)[1].lower()
                return self._file(os.path.join(WEB, name),
                                  CONTENT_TYPES.get(ext, "application/octet-stream"))

            if path == "/api/search":
                return self._json(search_photos(
                    q=one("q"), country=one("country"), city=one("city"),
                    scene=one("scene"), orient=one("orient"),
                    only_saved=one("saved") == "1",
                    page=max(1, int(one("page", "1") or 1)),
                    per=min(60, max(6, int(one("per", "24") or 24))),
                    min_pixels=int(one("minpx", "0") or 0),
                    hide_blur=one("noblur") == "1",
                    hide_wm=one("nowm") == "1",
                    hide_selfie=one("noselfie") == "1",
                    hide_solo=one("nosolo") == "1",
                    hide_dated=one("nodate") == "1",
                    hide_people=one("nopeople") == "1",
                    hide_graphic=one("nogfx") == "1",
                    hide_gray=one("nogray") == "1",
                    hide_car=one("nocar") == "1",
                    hide_junk=one("nojunk") == "1",
                ))

            if path == "/api/hide":
                pid = int(one("id", "0") or 0)
                val = 1 if one("value", "1") == "1" else 0
                conn = db()
                conn.execute("UPDATE photos SET hidden=? WHERE id=?", (val, pid))
                conn.commit()
                conn.close()
                _facets_cache.clear()
                return self._json({"ok": True, "id": pid, "hidden": val})

            if path == "/api/facets":
                return self._json(facets(one("country")))

            if path == "/api/ingest":
                q = one("q").strip()
                if not q:
                    return self._json({"ok": False, "msg": "缺少查询词"}, 400)
                n = ingest_query(q, one("country") or None, limit=30)
                return self._json({"ok": True, "added": n})

            if path == "/api/update":
                global _update_running
                if _update_running:
                    return self._json({"ok": True, "running": True})

                def _run():
                    global _update_running
                    _update_running = True
                    try:
                        with _ingest_lock:
                            update_latest(limit=30)
                    finally:
                        _update_running = False

                threading.Thread(target=_run, daemon=True).start()
                return self._json({"ok": True, "started": True})

            if path == "/api/status":
                conn = db()
                cnt = conn.execute("SELECT COUNT(*) c FROM photos").fetchone()["c"]
                conn.close()
                return self._json({
                    "last_update_at": get_meta("last_update_at", ""),
                    "last_update_added": get_meta("last_update_added", ""),
                    "running": _update_running,
                    "total": cnt,
                })

            if path == "/api/save":
                pid = int(one("id", "0") or 0)
                val = 1 if one("value", "1") == "1" else 0
                conn = db()
                conn.execute("UPDATE photos SET saved=? WHERE id=?", (val, pid))
                conn.commit()
                conn.close()
                _facets_cache.clear()
                return self._json({"ok": True, "id": pid, "saved": val})

            if path == "/img":
                u = one("u")
                if not u:
                    return self._json({"ok": False, "msg": "缺少图片地址"}, 400)
                try:
                    data, ctype = fetch_image(u)
                except Exception:
                    self.send_error(502)
                    return
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=604800")
                self.end_headers()
                self.wfile.write(data)
                return

            if path == "/download":
                u = one("u")
                name = one("name", "material.jpg")
                if not u:
                    return self._json({"ok": False, "msg": "缺少图片地址"}, 400)
                data, ctype = fetch_image(u)
                safe = re.sub(r'[\\/:*?"<>|]+', "_", name)[:80] or "material.jpg"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header(
                    "Content-Disposition",
                    "attachment; filename*=UTF-8''" + urllib.parse.quote(safe),
                )
                self.end_headers()
                self.wfile.write(data)
                return

            self.send_error(404)
        except BrokenPipeError:
            pass
        except Exception as e:
            try:
                self._json({"ok": False, "msg": str(e)}, 500)
            except Exception:
                pass


def main():
    init_db()
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "ingest":
            ingest_all()
            return
        if cmd == "ingest_dining":
            ingest_dining()
            return
        if cmd == "reclassify":
            reclassify_all()
            return
        if cmd == "clean":
            purge_rejected()
            return
        if cmd == "clean_life":
            purge_life_noise()
            return
        if cmd == "graphics":
            sc = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else None
            scan_graphics(scene=sc)
            return
        if cmd == "mediatype":
            scan_mediatype()
            return
        if cmd == "enrich":
            enrich_scan(limit=int(sys.argv[2]) if len(sys.argv) > 2 else None,
                        scene=sys.argv[3] if len(sys.argv) > 3 else None)
            return
        if cmd in ("gray", "car", "sign"):
            enrich_scan(only=cmd)
            return
        if cmd == "cats":
            scan_categories()
            return
        if cmd == "recolor":
            recolor()
            return
        if cmd == "calibrate":
            calibrate(sys.argv[2] if len(sys.argv) > 2 else "gray",
                      int(sys.argv[3]) if len(sys.argv) > 3 else 300)
            return
        if cmd == "refix":
            refix_thumbs()
            return
        if cmd == "update":
            update_latest(limit=25)
            return
        if cmd == "quality":
            quality_scan(limit=int(sys.argv[2]) if len(sys.argv) > 2 else None)
            return
        if cmd == "expand":
            sub = int(sys.argv[2]) if len(sys.argv) > 2 else 12
            pgs = int(sys.argv[3]) if len(sys.argv) > 3 else 2
            expand_deep(sub_limit=sub, pages=pgs)
            return
        if cmd == "life":
            ingest_life(limit=int(sys.argv[2]) if len(sys.argv) > 2 else 40,
                        batch=int(sys.argv[3]) if len(sys.argv) > 3 else 1)
            return
        if cmd == "device":
            ingest_device(limit=int(sys.argv[2]) if len(sys.argv) > 2 else 40)
            return
        if cmd == "status":
            conn = db()
            total = conn.execute("SELECT COUNT(*) c FROM photos").fetchone()["c"]
            vis = conn.execute("SELECT COUNT(*) c FROM photos WHERE hidden=0").fetchone()["c"]
            by_c = conn.execute(
                "SELECT country, COUNT(*) c FROM photos WHERE hidden=0 GROUP BY country"
            ).fetchall()
            checked = conn.execute(
                "SELECT COUNT(*) c FROM photos WHERE checked_at IS NOT NULL").fetchone()["c"]
            cities = conn.execute(
                "SELECT COUNT(DISTINCT city) c FROM photos WHERE city != '其他'").fetchone()["c"]
            conn.close()
            print("素材总数 %d（可见 %d）· 覆盖城市 %d 个" % (total, vis, cities))
            for r in by_c:
                print("  %s  %d" % (r["country"], r["c"]))
            print("质量检测已完成 %d 张" % checked)
            conn2 = db()
            for label, sql in [
                ("已扫描", "SELECT COUNT(*) c FROM photos WHERE enrich_at IS NOT NULL AND enrich_at > 0"),
                ("黑白照", "SELECT COUNT(*) c FROM photos WHERE COALESCE(is_gray,0)=1"),
                ("其中褐调", "SELECT COUNT(*) c FROM photos WHERE COALESCE(sepia,0)=1"),
                ("车辆特写", "SELECT COUNT(*) c FROM photos WHERE COALESCE(car_iso,0) >= %s" % CAR_ISO_THRESHOLD),
                ("标识照", "SELECT COUNT(*) c FROM photos WHERE COALESCE(junk_sign,0)=1"),
            ]:
                print("%s %d 张" % (label, conn2.execute(sql).fetchone()["c"]))
            conn2.close()
            print("上次更新 %s · 上次扩充 %s"
                  % (get_meta("last_update_at", "-"), get_meta("last_expand_at", "-")))
            return

    cfg = load_config()
    hour = int(cfg.get("auto_update_hour", 7))
    if cfg.get("auto_update", True):
        threading.Thread(target=scheduler_loop, args=(hour,), daemon=True).start()

    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("素材库已启动: http://127.0.0.1:%d" % PORT, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
