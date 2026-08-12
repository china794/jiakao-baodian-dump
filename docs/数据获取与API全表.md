# 驾考宝典数据获取与 API 全表

> 从 PC 客户端 renderer.js 挖端点、sign.dll 黑盒签名、本地 SQLite 解密，到 50 万条讨论区评论与 1736 条视频直链——整套采集体系的完整清单。

**规模**：33 车型 225,688 题 · 502,791 评论 · 21 域名密钥 · 45+ 端点
## 数据总览

这套体系从两条路拿数据：**本地离线**（客户端缓存的 SQLite 题库库，直接解密导出）与**在线 API**（签名机伪造合法请求，拉客户端未缓存的业务数据）。本地库是主粮，API 是增量。

| 数据域 | 规模 | 获取方式 | 状态 |
|---|---|---|---|
| 33 车型题库 | 225,688 题（car/bus/truck/moto/网约车/危险品…） | 本地 SQLite + XOR 解密 | ✅ 已归档 |
| VIP 解析 | 6,406 题 / 5,775 有解析 | API 批量签名采集 | ✅ 已归档 |
| 真题讨论区 | 6,406 题 / 502,791 评论 | API 分页采集（LIFO 队列） | ✅ 已归档 |
| 讲解视频 | 1,736 条元数据 | API 一次全量拉取 | ✅ 已归档 |
| 路线视频 | 321 城市 / 279 有数据 | API 层级探测 | ✅ 已归档 |
| 驾校 / 交通图标 / 课件 / 品牌 | 驾校 7.5MB + 图标 339KB + 课件 120KB | API 探测 | ✅ 已归档 |
| 排行榜 | 10,286 榜 / 56.8 万上榜人次 | API 无签名直连采集 | ✅ 已完成 |
| VIP练习 / 题库版本 / 题库下载 | 50 题ID / 版本确认 / CDN直链 | API 签名采集（参数已挖到） | ✅ 已实测 |

---
## 数据获取的四条路径

所有数据都来自这三条链路，外加一条签名机的核心支撑。每一条都是独立可复用的资产。

### 路径 A · 本地 SQLite 解密 离线 · 主粮

客户端运行时从官方下载全量库到本地 `tikuUpdate/db/*.db`（SQLite）。题干/解析是加密 blob，用 renderer.js 的 `decodeData()` 逻辑 XOR 解密。

- XOR key：`_jiakaobaodian.com_`（19 字节循环）
- car.db 6,406 题 · 版本 202608061421
- 33 库全量导出 → `exports/*.full.json`
- 媒体（图片/视频）从 `t_media` blob 直接导出

### 路径 B · 签名机伪造 API 在线 · 增量

对任一 `host + path + biz` 调 sign.dll 生成合法签名，拿到可访问的 `fullUrl`，再用普通 HTTP 拉数据。可采所有未缓存的业务数据。

- 批量模式：一次启动签 30 个请求
- 5 并发 + 0.15s 间隔 ≈ 5 QPS 安全线
- 已采：VIP解析 / 讨论区 / 视频 / 驾校 / 路线视频

### 路径 C · 登录态注入 需 authToken

authToken 只存 Pinia 内存，不进 localStorage。用 `inject_auth.js` hook 客户端 XHR，从请求 URL 偷 token 写入 `auth_token.txt`，签名机自动带上。

- 已注入成功，可采登录态数据
- 异地登录保护：>5 QPS 会触发验证
- 用户只需手动登录一次客户端过验证码

### 路径 D · 视频实时 URL API 服务

视频 CDN 直链的 `auth_key` 仅 5 分钟有效，预取无用。写了个常驻 HTTP 服务，播放时实时签新 URL。

- `/api/video?svid=x` 按视频 ID 解析
- `/api/video/by-question?qid=x` 按题号自动查
- 签名机常驻即随时随地可拉，无需用户

---
## 签名机机制

签名机是整个在线采集的引擎：一个 NW.js 脚本 `sign_runner/run.js` 用 ffi 调用客户端自带的 `sign.dll`，把任意请求参数变成合法签名。核心逻辑不靠反编译——直接黑盒复用 dll。

### 调用链

    Python 写 params.json→
    启动 驾考宝典.exe (main=run.js)→
    run.js require('ffi') 调 sign.dll→
    SignUrl(path?query, secret)→
    写 result.json→
    Python 拿 fullUrl

| 环节 | 细节 |
|---|---|
| sign.dll | Go 编译 x86 32 位 1.6MB，dist/static/lib/sign/。导 Init(sign.db) + SignUrl(input, secret) |
| 签名本质 | MD5。AES 只用于解密 sign.db（加密的密钥库），Init 时拿真正 secret |
| secret 表 | 21 个域名各一个，全写进 run.js SECRETS，从 renderer.js 挖出 |
| baseParams | 固定值 _appUser/1234567890 _deviceId _version 8.22.0，拼进 query 一起签名；authToken 有则带 |
| _r 参数 | n=abs(int(time*random*1e4)) → 数字和+len → _r=1+n+校验.zfill(3)，参与签名 |
| 批量模式 | {mode:"batch", reqs:[...30个]}，一次 exe 签 30 个，快一个数量级 |
| 坑 | UTF-8 BOM 会让 node JSON.parse 崩；采集完 main 必须恢复 ./dist/index.html；TCP 常驻方案因 NW.js 不保活事件循环放弃 |

### 登录态注入

    用户手动登录客户端→
    inject_auth.js hook XHR→
    URL 含 authToken → 写 auth_token.txt→
    签名机自动注入 baseParams

易盾验证码挡在登录处（captchaId `6f92317b6e7d4f4faa77a360d65826c5`），但只需用户手动过一次。之后所有请求自动带 token。

---
## API 端点行为全表

按域名分组，覆盖已采与可采的全部业务端点。参数为已验证的真实调用参数；已采 表示有归档数据，待挖 表示探通但未深采，新 表示刚挖出未验证。

panda.kakamobi.cn考试项目 · 路线视频 · 图标 · 课件

域名 secret `*#06#l5J2nW13…`。路线视频层级：area-list → place-list → list-data → detail。

| 路径 | 参数 | 行为 | 状态 |
|---|---|---|---|
| /api/open/exam-project/list.htm | kemu, tiku, cursor, pageSize:100, encodeVersion:1 | 考试项目列表，全车型/科目分页 | 已采 |
| /api/open/exam-project/get-car-brand-list.htm | kemu:1, tiku:car | 汽车品牌列表 | 已采 |
| /api/open/route-video/area-list.htm | cityCode | 地区列表（321 城探测） | 已采 |
| /api/open/route-video/place-list.htm | cityCode, areaCode | 考场列表 | 已采 |
| /api/open/route-video/show-entrance.htm | cityCode | 入口配置 | 已采 |
| /api/open/route-video/list-data.htm | cityCode, placeId, version | 路线视频数据 | 已采 |
| /api/open/route-video/detail.htm | id, placeId, version | 路线详情 | 已采 |
| /api/open/traffic-icon/group-list.htm | carType:car | 交通图标分组 | 已采 |
| /api/open/traffic-icon/icon-list.htm | groupId, carType | 图标列表 | 已采 |
| /api/open/kejian/project-list.htm | kemu:1 | 课件项目列表 | 已采 |
| /api/open/kejian/lecture-list.htm | projectId, kemu | 课件讲义列表 | 已采 |

jk-tiku.kakamobi.cn题库核心 · VIP · 视频 · 版本

核心题库域，secret `*#06#i4mleXFF…`。sceneCode 有讲究：VIP 解析用 `101`（顺序练习），重学用 `102`。

| 路径 | 参数 | 行为 | 状态 |
|---|---|---|---|
| /api/open/vip/question-explain.htm | carType, kemu, sceneCode:101, questionList:[题号] | VIP 解析（artfulDetail 巧记/concise 精简） | 已采 |
| /api/open/video-explain/get-video-list.htm | carType, kemu, sceneCode:101 | 讲解视频列表，一次全量 1,736 条 | 已采 |
| /api/open/relearn/question-list.htm | carType, seqnum, sceneCode:102, course, patternCode:101, kemuStyle, bizCode | 错题重学题目列表 | 已采 |
| /api/web/exam/san-li-exam-question-list.htm | _r | 三力测试题列表 | 已采 |
| /api/open/vip/vip-practice.htm | kemu, carType, cityCode, practiceType(vip-500/vip-100), dbVersion, sceneCode | VIP 练习题目ID列表 | 已实测 |
| /api/open/app-db/update-super.htm | majorVersion, sceneCode, version(JSON), applicationType:pc | 题库版本更新检查 | 已实测 |
| /api/open/app-db/download.htm | carType, majorVersion, applicationType:pc | 题库整库 CDN 直链下载 | 已实测 |
| /api/open/feedback/banner.htm | _r | 反馈 banner，返回题目列表 | 已采 |

dianping-v2.kakamobi.com真题讨论区 · UGC

placeToken 固定 `5bee2e55901b4de5b15b735eba3056fa`。cursor 是大整数，不能当 falsy 判断；每题最多翻 5 页。

| 路径 | 参数 | 行为 | 状态 |
|---|---|---|---|
| /api/open/dianping/list.htm | placeToken, topic:题号, cursor, _r | 每题评论列表（20/页，hasMore+cursor 分页） | 已采 |

short-video.kakamobi.cn原题视频

shortVideoId → CDN 直链 mp4，auth_key 5 分钟有效。

⚠️ **路线视频 CDN 双栈差异**：讲解视频（hw-qiche-video）**不校验** auth_key → 永久可播；路线视频（hw-jiakao-video）**校验** auth_key（限时约 24h）→ 过期 HTTP 403 不可播，需重采。2026-08-11 采集的路线视频快照已过期。

| 路径 | 参数 | 行为 | 状态 |
|---|---|---|---|
| /api/open/video/question-origin-video-detail.htm | idList:shortVideoId | 返回 itemList[0].videoUrl 直链 | 已采 |

jiakao-misc.kakamobi.cn杂项 · 通过率 · FAQ · 配置

无需登录即可拉的基础配置类。

| 路径 | 参数 | 行为 | 状态 |
|---|---|---|---|
| /api/open/pass-rate/get-pass-rate.htm | — | 通过率 | 已采 |
| /api/open/resource-config/get-resource-list.htm | — | 资源列表 | 已采 |
| /api/open/light-emulator/banner.htm | — | 灯光模拟 banner | 已采 |
| /api/open/operation-config/get-pc-live-operation.htm | — | PC 直播运营配置 | 已采 |
| /api/open/faq/list.htm | kemu:3, status:2, routeId, placeId | 路线视频 FAQ | 已采 |
| /api/open/config/get-config.htm | key | 全局配置 | 已采 |
| /api/web/must-exercise/get-detail.htm | listId:32 | 必练题（仅 1 个 listId，价值低） | 已采 |

panda / sirius / pony / squirrel / jiaxiao会员 · 权限 · 驾校

登录态相关端点，多数需要有效 authToken + 正确参数才有数据。

| 域名 | 路径 | 参数 | 状态 |
|---|---|---|---|
| sirius | /api/open/vip-level-info/get.htm | carType, sceneCode | 空返回 |
| pony | /api/open/user-member-identity/get-user-identity.htm | carType, sceneCode | 空返回 |
| pony | /api/open/permission/has-permissions.htm | permissions:vip, needValidate:true | 已采 |
| pony | /api/open/vip-badge/vip-badges.htm | carType, sceneCode | 空返回 |
| squirrel | /api/open/order/get-order-status.htm | orderNos | 空返回 |
| jiaxiao | /api/web/v3/jiaxiao/list-city.htm | cityCode | 已采 |

---
## 新挖出的端点（价值评估）

renderer.js 里挖出的第二批端点。其中排行榜用了**动态域名** `ke1/ke4/zige.jiakaobaodian.com`——按科目切换子域，与已知的 kakamobi 域名体系完全不同，且**不走签名**（只加随机 `_s`）。

| 域名 | 路径 | 行为 | 价值 |
|---|---|---|---|
| ke1/ke4/zige.jiakaobaodian.com | /api/open/h5/rank/list.htm | 排行榜，rankList[100] + myRank，按地区/时间过滤。✅已实测全通 | 高 · 10286榜已采 |
| ke1/ke4/zige.jiakaobaodian.com | /api/open/v2/score/submit.htm | 成绩提交（POST），用户考试分数 | 低 · 单用户 |
| jiakao-cloud.kakamobi.cn | /api/open/sync/fetch-all-data.htm | 用户做题进度/历史云同步 | 用户隐私 |
| auth.mucang.cn | /api/open/v3/scan-login/*.htm | 扫码登录二维码 + 轮询结果 | 登录链路 |
| auth.mucang.cn | /api/open/v3/login-sms/*.htm | 短信验证码登录 | 登录链路 |
| pony.kakamobi.cn | /api/open/different-places-login/*.htm | 异地登录短信验证 | 风控链路 |
| feedback.kakamobi.com | /api/open/v2/feedback/*.htm | 反馈系统（create/list/reply/view） | 低 |
| exam-statistics.kakamobi.cn | /api/open/practice/upload.htm | 练习统计上报 | 低 |
| oort-shipper.kakamobi.cn | /api/open/receiver/send.htm | 埋点/遥测上报 | 低 |
| util.kakamobi.cn | /h5/city-locate.htm | 城市定位 | 已采 |
| cheyouquan.kakamobi.cn | /api/open/business/jiakao/get-exam-share-configs.htm | 考试分享配置（仅 2 字段） | 已采 |

**四端点实测结果（参数已从 renderer.js 挖到真实调用代码）**：

| 端点 | 真实参数 | 实测结果 |
|---|---|---|
| rank/list | cityName, carType, cityCode, schoolCode, schoolName(必填), areaScope(city/school/province/country), timeScope(day/week/month/all), authToken(可选), _s | ✅ 全通。city 需 schoolName 非空。100人/榜 |
| vip-practice | kemu(1/4/zigezheng), carType, cityCode, practiceType(vip-500/vip-100), dbVersion(t_version.version), sceneCode | ✅ 返回 50 个题目 ID 列表 |
| app-db/update-super | majorVersion(t_version.major_version), sceneCode, version(JSON串，carType+version数组), applicationType:pc | ✅ 当前库最新，itemList 空 |
| app-db/download | carType, majorVersion, applicationType:pc | ✅ 返回 dbUrl CDN 直链 + dbMd5 + dbSize + totalCount |

关键参数全部来自本地 SQLite `t_version`：car.db `major_version=6`, `version=202608061421`。排行榜不签名。

---
## 已采数据明细

所有产出的最终落点，方便定位。

| 产物 | 路径 | 内容 |
|---|---|---|
| 33 库全题 | data/<车型>/questions.json | 每库题目 + 章节 + 考试规则 + 媒体 |
| 33 库解密全量 | exports/*.full.json | 含 XOR 解密正文（359MB） |
| VIP 解析 | harvested/vip-explain/all-vip-explain.json | 6,406 题，巧记/精简解析 |
| 真题讨论区 | harvested/dianping/all-dianping.json | 502,791 条评论，按题号索引 |
| 视频元数据 | harvested/video-explain/video-list-all.json | 1,736 条 shortVideoId + 封面 |
| 视频 URL 表 | harvested/video-explain/video-urls.json | 预取表（仅验证，auth_key 会过期） |
| 路线视频 | harvested/route-video/all-data.json | 279 城市 / 2,217 考场 / 6,114 视频（⚠️ 快照已过期 403，需重采） |
| 排行榜 | harvested/rank/all-rank.json | 10,286 榜 / 56.8 万上榜人次（166MB） |
| 驾校 | harvested/jiaxiao/all-schools.json | 全国驾校列表 |
| 图标/课件/品牌 | harvested/traffic-icon\|kejian\|exam-project/ | 交通图标、课件讲义、汽车品牌 |

### 采集脚本清单

| 脚本 | 用途 |
|---|---|
| scripts/sync_all.py | 主采集框架：签名 + HTTP + 33库同步导出 |
| scripts/harvest_api.py | 全端点采集器（ENDPOINTS 清单即 API 目录） |
| scripts/mine_all.py | 33 库本地挖掘 → exports/ |
| scripts/harvest_vip.py | VIP 解析全量（6,406 题） |
| scripts/harvest_dianping2.py | 讨论区全量（LIFO 队列 + 批量签名） |
| scripts/harvest_rank.py | 排行榜全量（无签名直连，10,286 榜） |
| scripts/harvest_auth.py | 登录态数据（重学/VIP/会员，依赖 authToken） |
| scripts/route_batch.py | 全国路线视频两阶段采集 |
| scripts/video_url_api.py | 讲解视频实时 URL 解析服务（端口 8790） |
| scripts/harvest_more.py | 第二批无登录端点 |
| scripts/harvest_deep.py | 全参数深度遍历 |
| scripts/export_per_db.py / export_full.py / export_media_all.py | 每库独立数据集 / 全库画像 / 媒体导出 |
| scripts/split_per_question.py / verify_relations.py | 逐题拆分前端按需加载 / 引用完整性校验 |
| scripts/probe_new.py / probe_new_ep.py / probe_endpoints_2.py | 一次性探针（已归档 archive/scripts/） |
| scripts/*_progress_server.py | 进度条服务器（端口 8765-8767） |
