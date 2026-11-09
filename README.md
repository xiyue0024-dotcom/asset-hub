# 印尼 · 新加坡素材库

个人自用的视觉素材检索工具：瀑布流图库 + 关键词搜索 + 城市/场景/横竖版筛选 + 灯箱查看 + 原图下载，每张素材都带完整版权与作者信息。

**设计原则：宁可返回空，也不返回错。** 搜不到就明确告诉你搜不到，绝不用不相关的图凑数。

## 启动

```bash
cd asset-hub
python server.py
```

打开 <http://127.0.0.1:8777>

不需要安装任何依赖，Python 标准库即可运行。

## 目录结构

```
asset-hub/
├── server.py            # 后端：采集适配器 + SQLite + 检索 API + 图片缓存代理
├── config.json          # 可选，填 Pexels 密钥
├── data/
│   ├── library.db       # 素材库（SQLite）
│   └── imgcache/        # 图片磁盘缓存，二次访问秒开
└── web/
    ├── index.html
    ├── style.css
    └── app.js
```

## 搜索怎么工作的

不是纯向量检索，而是**结构化过滤 + 关键词全命中**两级：

1. 先用 SQL 过滤 `国家 / 城市 / 场景 / 横竖版`，把候选从几千张缩到几百张；
2. 再要求**查询里的每个关键词都出现**，才算一条结果；按命中位置打分（命中标题权重 3，命中标签/描述权重 1）。

这个组合比纯向量搜索更快、更可控，而且不需要 GPU。素材量涨到几万张以上时，再把第二步换成 CLIP 向量召回。

## 检索为什么不会给你错图

多数素材机器人是「取相似度最高的前 N 张」直接返回，哪怕只有 50% 相关度也照样推给你，而且不提示。这个库反过来，**先判定有没有资格返回**：

| 状态 | 判定条件 | 界面表现 |
|---|---|---|
| **精确匹配** | 查询里每个关键词都命中 | 正常显示，标注「精确匹配 N 张」 |
| **弱匹配** | 只命中部分关键词，且没有任何精确结果 | 顶部黄色警示条 + 每张图打「弱匹配 xx%」角标 |
| **无匹配** | 一个关键词都没命中 | 不显示任何图片，明确告知「没有找到」，并提供补采/换词入口 |

三种状态互斥，弱匹配结果**永远不会**混在精确结果里冒充答案。灯箱里也能看到单张图的匹配度。

## 素材会自己更新

素材库不是固定快照。有三种更新方式：

**1. 服务常驻时自动更新（默认开启）**

服务启动后会起一个后台线程，每天到了设定时间自动跑一次增量更新。默认 7 点，在 `config.json` 里改：

```json
{ "auto_update": true, "auto_update_hour": 7 }
```

**2. 界面手动触发**

右上角「↻ 抓取最新」按钮，点一下后台开始跑，跑完自动刷新。

**3. 命令行 / 定时任务**

```bash
python server.py update     # 每分类取最新 100 张（约 4 分钟）
python server.py expand     # 深度扩充：翻页 + 进子分类（约 30-40 分钟）
python server.py quality    # 质量检测：清晰度 + 水印风险
```

`expand` 是量的主要来源：每个分类往下翻 6 页（600 张），再进入最多 6 个子分类各取一页。相比 `update` 只取首屏 100 张，量级差 10 倍以上。

想让它完全不依赖服务是否开着，用 Windows 计划任务每天固定时间跑：

```bat
schtasks /create /tn "素材库每日更新" /tr "cmd /c cd /d C:\path\to\asset-hub && python server.py update" /sc daily /st 07:00
```

### 更新是怎么抓「最新」的

**不是**按时间排序全文搜索——那样会捞出完全无关的图（实测搜 `Bali beach` 按时间排，第一条是音乐人照片）。

用的是 Commons 的**分类**：`Category:Bali`、`Category:Cafés in Singapore`、`Category:Hawker centres in Singapore` 等 20 个分类，每个分类按**上传时间倒序**取最新文件。分类本身是精确的，所以既新又不会跑题。

去重靠两个唯一索引：`source_id`（同一条记录不重复入库）和 `title_key`（同名多副本只留一张）。所以重复跑更新不会产生垃圾，只会补进真正新的素材。

单次更新约 2 分钟，实测新增 300+ 张。

## 部署到 GitHub Pages（团队访问）

这套东西有两份产物，用途不同：

| | 本地版 | 静态版 |
|---|---|---|
| 入口 | `python server.py` → 127.0.0.1:8777 | `docs/` 目录 |
| 检索 | Python 后端 | 浏览器内 JS，逻辑完全一致 |
| 素材来源 | 实时抓取 + 本地库 | 预导出的 JSON 索引 |
| 图片 | 本地磁盘缓存代理 | 直连 Wikimedia CDN |
| 适合 | 自己用 | 团队访问 |

### 步骤

**1. 上传到 GitHub**

把 `asset-hub` 目录里的内容（不是目录本身）作为仓库根上传，确保根目录能看到 `server.py`、`docs/`、`.github/`。

**2. 开启 Pages**

仓库 Settings → Pages → Source 选 `Deploy from a branch` → Branch 选 `main`，目录选 `/docs` → Save。

一分钟后访问 `https://<你的用户名>.github.io/<仓库名>/`，团队拿这个链接就能用。

**3. 开启 Actions 写权限**

Settings → Actions → General → Workflow permissions → 选 `Read and write permissions` → Save。

不然每日更新跑完推不回去。

**4. 自动更新已经配好**

`.github/workflows/update.yml` 会在**每天 UTC 23:00（北京时间 07:00）**自动执行：

```
python server.py update   # 按分类抓最新素材
python build_static.py    # 重新导出 docs/
git commit & push         # 页面自动重建
```

也可以在 Actions 页面点 `Run workflow` 手动触发。

### 静态版的三个限制

1. **不能「下载原图」**。跨域链接的 `download` 属性浏览器会忽略，所以按钮改成「打开原图」，在新标签页右键另存。
2. **收藏存在各自浏览器里**（localStorage），团队之间不共享，换设备也不同步。
3. **Pages 是公开的**。免费账号的 Pages 站点任何拿到链接的人都能访问。要真正私有，得用 GitHub Enterprise Cloud，或者换 Cloudflare Pages + Access。

### 手动导出

```bash
python build_static.py          # 输出到 docs/
python build_static.py out_dir  # 输出到指定目录
```

索引约 2.3 MB，gzip 后 322 KB，首次加载一两秒。

## 素材质量过滤

界面上有一排「质量过滤」开关，默认开启前三项：

| 开关 | 判定方式 | 默认 |
|---|---|---|
| 只看高清 | 分辨率 ≥ 100 万像素（约 1200×800） | 开 |
| 隐藏疑似水印 | 图像四角边缘密度显著高于中心 → 判为角标/水印/日期戳 | 开 |
| 隐藏自拍/单人像 | 标题含 selfie / portrait / "man with…" 等单人特征，且不含 group / crowd / family 等群体词 | 开 |
| 隐藏模糊 | 边缘强度低于阈值 | 关 |

**自拍与单人像的判定逻辑**：先看是不是自拍（selfie、"me at"、"my wife"），再看有没有群体词（group / crowd / family / dance / festival / buffet）。**有群体词的保留**——所以聚餐、宴席、节庆这类不漏拍摄者的合影不会被误杀。

### 关于水印：为什么是「过滤」而不是「擦除」

自动去水印技术上不可靠（会留下明显涂抹痕迹），而且 **CC BY-SA 协议的图抹掉作者水印属于破坏署名**，超出个人合理使用范围。所以这里做的是**识别并隐藏**，不是修改图片。

如果实在需要那张图，灯箱里有「打开原图」，可以自行处理。

### 手动兜底

自动判定一定会有漏网。灯箱底部有 **「隐藏此图（水印/人物）」**，点一下这张图就永久隐藏（存在本地库里，静态版存在浏览器 localStorage）。

### 跑质量检测

视觉检测需要下载缩略图逐张分析，是个耗时任务，支持断点续跑：

```bash
python server.py quality        # 检测所有未检测的
python server.py quality 200    # 只检测 200 张
```

4000 张大约需要 1 小时（受 Wikimedia 限流影响）。检测结果会写进 `blur_score` / `corner_score` / `wm_suspect`，界面上的「疑似水印」「隐藏模糊」开关随之生效。

### 关于文件名里的日期

有些照片文件名带 `20220827 1721` 这样的时间戳，但**图上并没有日期戳**（抽查确认过）。所以按文件名过滤会误杀大量好图，这个规则默认不启用——真正带日期戳的图会被角落检测识别为「疑似水印」。

## 接入外部图库（真实生活分享优先）

默认只用 Wikimedia Commons，免费无需密钥，内容本身就是普通人的实拍。

**不申请任何 KEY 也能用。** 真实生活素材的关键不是换图库，而是换关键词——之前按「地标/景点」抓，出来全是风景照；按「生活场景」抓完全是另一回事：

```bash
python server.py life
```

覆盖印尼的 `warung makan`（小饭馆）、`kaki lima`（路边摊）、`pasar pagi`（早市）、`angkringan`、`ojek`、`kampung`、`gang`，以及新加坡的 `kopitiam`、`void deck`、`HDB corridor`、`heartland`、`wet market`、`tiong bahru`。抓回来是「小店内部」「菜摊」「组屋走廊」这类真实场景。

### 一、Flickr：仅限 Pro 订阅（不推荐）

**注意**：Flickr 已改为「**只有 Pro 订阅用户才能申请 API 密钥**」，免费账户通过 API 只能下载不超过 1024 像素的图。Pro 约 7 美元/月。

已有 Pro 才需要这步：<https://www.flickr.com/services/apps/create/> → **Apply for a Non-Commercial Key** → 填应用名 → 拿 Key。代码只抓 CC 授权子集（`license=1,2,3,4,5,6,9,10`）。

### 二、Pexels（可选）

1. 打开 <https://www.pexels.com/api/>，点 **Get Started** 注册
2. 填名字 + 用途（`personal travel photo reference`）+ 勾条款
3. 点 **Generate API Key**，立刻显示
4. 额度：200 次/小时，20,000 次/月

### 三、Pixabay（可选）

1. 打开 <https://pixabay.com/api/docs/>，注册并登录
2. **重新打开**该文档页，顶部会显示你的 Key
3. 额度：100 次/分钟

### 关于 Unsplash：不推荐

Unsplash 是签约摄影师的作品库，统一调色、黄金时刻、刻意留白，本质是**给品牌海报用的商业素材**，缺少真实生活的粗糙感。适配器保留着（`unsplash_access_key`），但除非你确实需要精修质感，不必申请。

### 填到哪里

在 `asset-hub` 目录下建 `config.json`：

```json
{
  "flickr_api_key": "你的 Flickr Key",
  "pexels_api_key": "你的 Pexels Key",
  "pixabay_api_key": "你的 Pixabay Key"
}
```

填几个都行，不填的会自动跳过。重启服务后，补采和自动更新会同时写入这几个来源。

`config.json` 已经在 `.gitignore` 里，不会被提交到仓库。

### 部署到 GitHub 后怎么用密钥

密钥不要写进仓库。在仓库 **Settings → Secrets and variables → Actions → New repository secret** 里分别添加：

- `FLICKR_API_KEY`
- `PEXELS_API_KEY`
- `PIXABAY_API_KEY`

`.github/workflows/update.yml` 已经把这三个 secret 通过环境变量传给采集脚本了。

### 授权差异

| 来源 | 是否要署名 | 内容风格 |
|---|---|---|
| Wikimedia Commons | **要求** | 普通用户实拍，真实但质量参差 |
| Flickr（CC 子集） | **要求**（CC BY 系） | 最接近真实生活分享 |
| Pexels / Pixabay | 不要求 | 半商业，偏干净 |
| Unsplash | 不要求 | 精修商业素材，不推荐 |

## 素材从哪来

默认接的是 **Wikimedia Commons**，免密钥、可直接调用，而且每张图都带 `License` 和 `Artist` 字段——这是它比"从群组里抓图"更值得用的原因：**来源可追溯**。

想接 Pexels（免费可商用、画质更好）只需两步：

1. 到 <https://www.pexels.com/api/> 注册，拿到免费密钥；
2. 在同目录建 `config.json`：

```json
{ "pexels_api_key": "你的密钥" }
```

重启服务后，采集会自动同时写入两个来源。

## 加更多素材

三种方式：

- **界面上补采**：搜索框输入关键词，点右上角「＋ 补采素材」；
- **命令行批量**：编辑 `server.py` 里的 `SEEDS` 列表，然后 `python server.py ingest`；
- **自动补采**：搜索时本地命中不足 8 张，会自动去公开图库拉一批入库（5 分钟内同一关键词不重复请求）。

## 采集的几个坑（已经处理）

| 问题 | 现象 | 处理 |
|---|---|---|
| API 限流 | 连续请求后返回 429，整批失败 | 请求间隔 1.8–3s + 指数退避重试 |
| 地名歧义 | "Bali, Crete"（希腊）被当成印尼巴厘岛 | 关键词黑名单过滤 |
| 境外误入 | 搜 "Singapore cafe" 捞回呼和浩特/香港/澳洲的图 | 境外地名黑名单 + 中文标题无本地信号则剔除 |
| 重复素材 | 同一张图有 `(1)` `(2)` 多个副本 | 标题归一化后建唯一索引 |
| 缩略图 404 | Wikimedia 只认固定几档宽度，600px 全部裂图 | 对齐到 250/500/960/1280/1920 |
| UA 被拒 | 请求头里带占位邮箱域名直接 403 | 换成标准 UA |
| 时间排序跑题 | 按上传时间搜 `Bali beach`，返回音乐人照片 | 改用分类抓取，不用时间排序 |
| **相关度不足仍返回** | 搜「苹果耳机」推 iPhone 图，标 52% 相关度还当结果给 | **全部关键词必须命中**，否则降级为弱匹配并显式警告，无匹配则返回空 |

## 版权说明（个人使用）

这个库是**个人自用**，不做对外分发。即便如此，每张图仍保留 `License` 和 `Artist` 字段：

- Wikimedia Commons 的图多为 CC BY-SA / CC BY，个人使用没有障碍；哪天要公开或商用，灯箱里的「复制署名」会生成标准署名文本，粘贴即可。
- 如果以后要交付给客户，建议切到 Pexels / Unsplash（不要求署名），或者用自有实拍素材。

## 下一步：包成 Telegram Bot

前端和检索层不用动，只需加一个 Bot 进程：

1. 找 @BotFather 建 Bot，拿 token；
2. 监听 `inline_query`——用户在任意群输入 `@你的bot 巴厘岛 海滩` 时，把关键词转发给本服务 `/api/search`；
3. 把返回的 `items` 组装成 `InlineQueryResultPhoto` 数组（`thumb_url` 用 `thumb`，`photo_url` 用 `full`），回给 Telegram。

检索逻辑、素材库、分类全部复用，Bot 层代码量很小。也可以直接把 `/api/search` 接给微信小程序或任何前端。
