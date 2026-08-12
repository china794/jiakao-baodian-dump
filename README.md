# 驾考宝典数据浏览器

驾考宝典全量数据逆向采集 + 数据浏览器。从 0 到 225,688 题全量题库 + 50 万讨论区评论 + 排行榜/驾校/路线视频/讲解视频等 12 大数据域。

> 本仓库是**纯净源码版**：只含采集/导出/前端源码 + 数据源（33 个官方题库 SQLite）+ 技术文档。**不包含**任何生成物（`data/<车型>/`、`exports/`、`media/`、`harvested/`、`frontend/by_qid/` 等），这些需按下方「从数据源重建」流程在本地生成。

## 快速开始

```bash
# 1. 安装依赖（Python 3.8+）
pip install -r requirements.txt

# 2. 从数据源 dbs/ 导出到 data/（33 库全量 → data/<车型>/）
python scripts/export_per_db.py

# 3. 启动本地服务器
python frontend/server.py
# 浏览器打开 http://127.0.0.1:8700/frontend/index.html
```

前端是纯静态页面（`frontend/index.html`，无构建），读 `data/` + `frontend/*.json` + `frontend/by_qid/` 按需加载。

## 数据规模（版本 202608061421）

| 数据域 | 规模 | 落点 |
|---|---|---|
| 33 车型题库 | **225,688 题** | `data/<车型>/questions.json` |
| 真题讨论区 | 502,791 评论 / 6,406 题 | `frontend/by_qid/<题号>.json` |
| VIP 解析 | 6,406 题 / 5,775 有解析 | `data/car/questions.json` 每题 `vip_explain` |
| 讲解视频 | 1,736 条 | `harvested/video-explain/video-list-all.json` |
| 排行榜 | 10,286 榜 / 56.8 万上榜人次 | `harvested/rank/all-rank.json` |
| 路线视频 | 279 城市 / 2,217 考场 / 6,114 视频 | `frontend/route_index.json` |
| 驾校 | 全国驾校 | `harvested/jiaxiao/all-schools.json` |

> 题库部分（33 库）可由 `dbs/` 数据源完整重建；讨论区/排行榜/视频等业务域需签名机在线采集（见下）。

## 从数据源重建（离线）

33 个官方题库 SQLite 在本仓库 `dbs/`（可直接从官方 CDN 下载，见 `scripts/sync_all.py`）。导出管线：

```bash
python scripts/sync_all.py sync          # 检查/更新 dbs/（联网，需签名机）
python scripts/export_per_db.py          # 每库独立数据集 → data/<车型>/
python scripts/mine_all.py               # 全库元数据 → exports/
python scripts/export_media_all.py       # 媒体 blob → media/<车型>/
python scripts/split_per_question.py     # 逐题拆分 → data/<车型>/q/ （前端按需加载）
python scripts/extract.py --region 福州  # 按需过滤交付
```

数据链路：`官方 CDN → 签名机 API → dbs/*.db → XOR 解密（key _jiakaobaodian.com_）→ data/<车型>/`。媒体由 car.db 主库跨库补全 + sha1 去重。

## 在线业务域采集（需签名机）

讨论区/VIP解析/排行榜/视频/驾校等业务域，通过客户端 `sign.dll` 签名机伪造合法 API 请求采集。签名机是**外部进程**（NW.js + 驾考宝典.exe），不在本仓库。

```bash
# 业务域采集脚本（scripts/）
harvest_vip.py         # VIP 解析全量
harvest_dianping2.py   # 讨论区全量（LIFO + 批量签名）
harvest_rank.py        # 排行榜全量（无签名直连）
route_batch.py         # 全国路线视频
video_url_api.py       # 讲解视频实时 URL 服务（端口 8790）
```

采集产物进 `harvested/`，再跑 `frontend/prep.py`（讨论区拆题号 + 排行榜索引）与 `frontend/prep_route.py`（路线视频索引）转前端可读格式。

## 目录结构

```
├── dbs/         33 个车型 SQLite（官方题库数据源，349MB）
├── scripts/     采集/导出/服务脚本（19 个正式 + archive/ 探针）
├── frontend/    前端 index.html + server.py + prep*.py
├── docs/        技术路线全记录 + API 全表
├── archive/     废弃/一次性探针脚本
└── .gitignore   生成物全部忽略（data/exports/media/harvested/by_qid）
```

## 文档

- `docs/全技术路线整理.md` — 完整逆向过程：端点挖掘、sign.dll 签名破解、XOR 解密、各域采集方案、踩坑记录
- `docs/数据获取与API全表.md` — API 端点行为全表（按域名分组）+ 数据明细

## 安全与合规

本项目仅用于**本地个人数据研究**。所有数据来自官方客户端公开接口，仅用于个人学习与离线浏览。**请勿**用于商业用途、对外分发原始数据、或绕过任何商业版权。

## 已知限制

- **路线视频会过期**：CDN auth_key 约 24h 失效，过期 HTTP 403 不可播，需重采刷新（讲解视频 CDN 不校验 auth_key，永久可播）
- **签名机是外部依赖**：不在本仓库，需 `sign_runner/` + 驾考宝典.exe 本体才能在线采集
- **讲解视频播放走实时 URL**（auth_key 5 分钟过期，每次播放实时调 `video_url_api.py:8790`）
