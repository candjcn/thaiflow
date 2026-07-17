# ReelSpeak — 项目全面交接文档

**写作时间**: 2026-07-17  
**用途**: 给接手 AI 的完整上下文，直接开工无需追问

---

## 一、项目是什么

**ReelSpeak** 是一个通过短视频学外语的 Web 应用。用户粘贴 TikTok/YouTube 链接（或上传本地视频），系统自动：
1. 语音识别 → 分句字幕
2. 翻译（双语字幕）
3. 逐句循环播放 / 影子跟读（录音 + AI 发音评分）
4. 生成 TTS 音频课程（可上传到 R2 分享）

**当前阶段**: 个人工具正在向多用户产品转型。Commerce（计费）平台正在建设中，Phase 0-2 已完成，Phase 3 集成进行中。

**线上地址**: https://getreelspeak.com（Railway 部署，GitHub `candjcn/thaiflow` push main 自动部署）  
**本地运行**: `python backend/app.py` → http://localhost:5000

---

## 二、技术栈（硬性限制，不可更改）

| 层 | 技术 | 约束 |
|---|---|---|
| 前端 | 纯原生 HTML/CSS/JavaScript | **禁止引入任何框架（React/Vue/Svelte）和打包工具** |
| 后端 | Python + Flask | 单文件入口 `backend/app.py` |
| 数据库 | SQLite（本地/开发）| Commerce 数据，路径 `/data/commerce.db`（Railway Volume 持久化）|
| AI 调用 | 全部云端 API | 无 GPU，所有 AI 必须走外部 API |

---

## 三、目录结构（完整）

```
videoplayer/
├── ARCHITECTURE.md          ★ 核心架构文档（必读）
├── CLAUDE.md                ★ 产品规格 + 技术约束（必读）
├── DEVELOPMENT_GOVERNANCE.md ★ 开发规范 + 决策记录
├── VISION.md                产品愿景
├── ROADMAP.md               发布计划（Phase 0-5）
├── HANDOVER.md              本文档
│
├── frontend/                纯原生 HTML/CSS/JS
│   ├── index.html           播放器应用（路由 /app）
│   ├── landing.html         公开首页
│   ├── player.js            播放器主逻辑（~1340行，渐进式模块化中）
│   ├── i18n.js              国际化，6语言，版本号 v=20260717c
│   ├── style.css            全局样式
│   ├── landing.css          首页样式
│   ├── profile.html         用户个人页（订阅/余额/推荐）
│   ├── profile.js           个人页逻辑
│   ├── usage.html           使用记录详情页（新增）
│   └── manifest.json        PWA 清单
│
├── backend/
│   ├── app.py               Flask 路由唯一入口（~1340行）
│   ├── export.py            SRT / 带字幕视频导出
│   ├── r2.py                Cloudflare R2 上传
│   ├── requirements.txt     Python 依赖
│   ├── .env                 本地环境变量（gitignored）
│   │
│   ├── config/              ★ 配置唯一入口（所有 env 读取在此）
│   │   ├── __init__.py      导出 settings, providers, get_logger
│   │   ├── settings.py      所有 os.getenv() 集中在此
│   │   ├── providers.py     各服务商 Base URL / 模型名 / 静态配置
│   │   └── logger.py        统一日志工厂（禁止用 print）
│   │
│   ├── ai/                  AI 能力层（按能力划分，不按服务商）
│   │   ├── speech.py        语音识别（groq/openai/azure/combined/qwen）
│   │   ├── translation.py   翻译 + 单词释义
│   │   ├── tts.py           TTS 课程生成
│   │   ├── pronunciation.py 发音评估（Azure only）
│   │   ├── romanize.py      拼音/罗马拼音
│   │   └── provider/        Provider 适配层（只被 ai/ 层调用）
│   │       ├── groq.py
│   │       ├── openai_whisper.py
│   │       ├── azure.py
│   │       ├── gemini.py
│   │       ├── deepseek.py
│   │       ├── youdao.py
│   │       ├── cloudflare.py
│   │       └── qwen_asr.py  ★ 新增，见下方说明
│   │
│   ├── domain/              领域模型（纯数据结构，无IO）
│   │   ├── segment.py       Segment（字幕分句）
│   │   ├── subtitle.py      SubtitleFile
│   │   ├── word.py          Word（词级时间戳）
│   │   ├── tts_script.py    TtsScript
│   │   ├── definition.py    Definition
│   │   └── pronunciation.py PronunciationResult
│   │
│   ├── commerce/            ★ 计费平台（Phase 0-2 完成，Phase 3 进行中）
│   │   ├── __init__.py      导出 get_db, CommerceContext
│   │   ├── db.py            SQLite 初始化 + 连接管理
│   │   ├── schema.sql       完整 DDL（表结构见下方）
│   │   ├── seed.py          初始数据（套餐/成本/定价策略）
│   │   ├── identity.py      用户身份
│   │   ├── wallet.py        Credits 账本（reserve/confirm/release）
│   │   ├── pricing.py       Capability → Credits 估算
│   │   ├── permission.py    权限引擎
│   │   ├── router.py        AI Provider 路由
│   │   ├── usage_log.py     AI 调用结构化记录（已新增 offset 分页）
│   │   ├── middleware.py    CommerceContext（调用链编排）
│   │   ├── rate_limit.py    限流（Free 用户每日上限）
│   │   ├── cron.py          后台任务（月度积分重置）
│   │   ├── auth.py          OAuth2 Google + Session 管理
│   │   ├── referral.py      推荐返利系统
│   │   ├── reconcile.py     账户对账审计
│   │   └── cost_engine.py   离线成本核算（运营分析用，不影响用户账户）
│   │
│   └── tests/               pytest 单元测试
│       ├── test_phase0.py   DB + Identity
│       ├── test_phase1.py   Wallet + Pricing + UsageLog
│       ├── test_phase2.py   Permission + Router
│       ├── test_phase3.py   API 集成测试
│       ├── test_phase4.py   Admin API
│       ├── test_phase5.py   生产加固
│       └── test_referral.py 推荐系统
│
└── videos/                  视频 + 字幕 JSON（不持久化，Railway 重部署清空）
```

---

## 四、环境变量（backend/.env）

当前本地 `.env` 内容：

```bash
# 语音识别
GROQ_API_KEY=<见 backend/.env>
OPENAI_API_KEY=<见 backend/.env>

# 翻译
DEEPSEEK_API_KEY=<见 backend/.env>

# 发音评估
AZURE_SPEECH_KEY=<见 backend/.env>
AZURE_SPEECH_REGION=southeastasia

# Gemini（多用途：TTS/翻译/图像/OCR）
GEMINI_API_KEY=<见 backend/.env>

# 管理后台
ADMIN_KEY=<见 backend/.env>

# Cloudflare R2（TTS 音频存储）
R2_ACCOUNT_ID=<见 backend/.env>
R2_ACCESS_KEY_ID=<见 backend/.env>
R2_SECRET_ACCESS_KEY=<见 backend/.env>
R2_BUCKET_NAME=reelspeak-audio
R2_PUBLIC_URL=https://pub-c00d464d3bb5416d952be95db7a51106.r2.dev
CF_AI_API_TOKEN=<见 backend/.env>

# Qwen3-ASR（阿里云 DashScope）★ 新增
DASHSCOPE_API_KEY=<见 backend/.env>
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/api/v1
DASHSCOPE_UPLOAD_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/files

# Google OAuth
GOOGLE_REDIRECT_URI=http://localhost:5000/api/auth/google/callback
```

> 真实值保存在 `backend/.env`（本地文件，gitignored），Railway 生产环境中直接配置为环境变量。

**Railway 生产环境额外需要**：
```bash
COMMERCE_DB_PATH=/data/commerce.db
PORT=5000
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://getreelspeak.com/api/auth/google/callback
```

---

## 五、层间调用规则（强制约束，违反即 Bug）

```
允许：
  app.py       → config/, ai/, commerce/, domain/, export.py, r2.py
  ai/          → config/, ai/provider/, domain/
  commerce/    → config/
  domain/      → 无外部依赖

禁止：
  ai/          → commerce/      （AI层不感知计费）
  commerce/    → ai/provider/   （Commerce 不直接调 Provider）
  app.py       → ai/provider/   （必须经过 ai/ 层）
  任何文件      → os.getenv()    （必须经过 config/settings.py）
  任何文件      → print()        （必须用 get_logger）
```

---

## 六、API 端点一览

### 公开 / 播放器
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 首页 landing.html |
| GET | `/app` | 播放器 index.html |
| GET | `/profile` | 个人页 profile.html |
| GET | `/usage` | 使用记录 usage.html |

### AI 能力
| 方法 | 路径 | 说明 | 主要参数 |
|------|------|------|---------|
| POST | `/api/download-video` | 下载 TikTok/YouTube | `url` |
| POST | `/api/upload-video` | 上传本地文件 | multipart file |
| POST | `/api/transcribe` | SSE 转录整段视频 | `video`, `engine`, `language` |
| POST | `/api/retranscribe` | 重识别某一句音频 | `audio`（blob）, `engine`, `index` |
| POST | `/api/translate` | 翻译字幕 | `video`, `segments`, `target_lang` |
| POST | `/api/word-define` | 单词释义 | `text`, `language` |
| POST | `/api/tts-content` | AI 生成 TTS 课程内容 | `text`, `target_lang` |
| POST | `/api/tts-generate` | 合成 TTS 音频课程 | `script`, `voices`, `provider` |
| POST | `/api/pronounce` | 发音评分 | `audio`（blob）, `text`, `language` |
| POST | `/api/romanize` | 生成拼音/罗马拼音 | `text`, `language` |
| POST | `/api/ocr` | 图片文字提取 | `image`（file） |
| POST | `/api/export-srt` | 导出 SRT | `segments`, `video` |
| POST | `/api/export-video` | 导出带字幕视频 | `segments`, `video` |

### 账户 / 计费
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/auth/google/login` | Google OAuth 跳转 |
| GET | `/api/auth/google/callback` | OAuth 回调（设 Cookie）|
| POST | `/api/auth/logout` | 登出 |
| GET | `/api/user/profile` | 用户信息 + 钱包余额 |
| GET | `/api/user/wallet` | Credits 明细 |
| GET | `/api/user/usage` | 使用记录（支持 `limit`+`offset`+`since_days` 分页）|
| POST | `/api/user/referral/generate` | 生成邀请码 |
| GET | `/api/user/referral/status` | 推荐状态 |

### Admin
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/admin/logs?key=ADMIN_KEY` | 使用日志 |
| GET | `/api/admin/commerce/*` | Commerce 管理接口 |

---

## 七、Commerce 平台详解

### 数据库表（schema.sql）

```
users                  用户基本信息（user_id UUID, email, status）
plan_definitions       套餐定义（free/plus/pro/enterprise + 月度积分）
user_subscriptions     用户订阅关系（plan + expires_at + credits_quota）
wallets                Credits 账本（subscription/gift/paid 三个桶 + version 乐观锁）
wallet_transactions    所有积分流水（reserve/confirm/release/add/refund）
provider_costs         Provider API 真实成本（per_minute/per_1k_tokens 等）
pricing_policies       Capability → Credits 定价策略（cost_multiplier 或 fixed）
usage_logs             每次 AI 调用记录（actual_units/latency/status 等）
permission_grants      手动权限授予（admin 操作）
user_identities        OAuth 绑定（Google）
user_sessions          登录 Session（token + expires_at）
referrals              推荐关系（referrer_id → referred_id + ref_code）
```

### Credits 扣款流程（v1.1，已定稿）

```
1. Identity.resolve(user_id)      → 当前过渡期全部用 "anonymous"
2. Permission.check(permission)   → 无权限 403
3. Pricing.estimate(input_meta)   → 估算 Credits（含 10% buffer）
4. Wallet.reserve(amount)         → 预扣，获得 reservation_id，不足 402
5. [Provider 调用]
6. UsageLog.record(actual_units)  → 记录实际用量（用于离线成本分析）
7. Wallet.confirm(reservation_id) → 消费确认（不重算，用 estimate 为最终扣款）

[失败时]:
   Wallet.release(reservation_id) → 全额释放
   UsageLog.record(status="failed")
```

**关键设计决策**：
- `Wallet.confirm()` **不重新计算** Credits，直接确认 estimate。真实成本只进 UsageLog，由 Cost Engine 离线分析。
- 这避免了 SSE 长流（30秒转录）中 Billing 事务长时间开放的问题。

### 套餐权限

| 套餐 | 月度 Credits | 质量档位 | 特殊权限 |
|------|------------|---------|---------|
| free | 100 | economy | 基础功能 |
| plus | 1000 | standard | + 标准质量 |
| pro | 5000 | premium | 全部权限 |
| enterprise | 50000 | premium | 全部权限 |

**新用户礼包**: 已取消，登录用户的基础权益由 free 套餐的 monthly_credits 提供。

### AI Router 路由表

```python
transcription:  economy/standard → [groq, azure]    premium → [azure, groq]
translation:    economy/standard → [deepseek, gemini]  premium → [gemini, deepseek]
tts_synthesis:  economy → [azure, gemini]  standard/premium → [gemini, azure]
pronunciation:  [azure]（唯一，无 fallback）
romanize:       [local(pypinyin), gemini]
```

---

## 八、前端关键细节

### i18n 使用规范

每次改动涉及前端新文案时，必须：
1. 在 `frontend/i18n.js` 中所有 6 个语言（zh-CN/zh-TW/en/ja/ko/th）都加翻译
2. 更新引用 `i18n.js` 的页面版本号，格式 `i18n.js?v=YYYYMMDDX`（日期+序号，如 `?v=20260717c`）
3. 当前最新版本号：`v=20260717c`（已在 index.html/landing.html/profile.html/usage.html 更新）

### player.js TDZ 防护

player.js 顶层执行语句必须全部在文件最底部的 `// ========== 启动初始化 ==========` 区块内：

```javascript
// ========== 启动初始化 ==========
I18N.init();
loadVideoList();
renderFavorites();
```

不得在声明前使用变量（TDZ 崩溃曾经是历史 Bug）。

### 移动端判定

宽度 ≤1024px 或触屏（平板也算手机 UI）：
```css
@media (max-width: 1024px), (pointer: coarse) { ... }
```

### 缓存控制

`app.py` 的 `@app.after_request` 已设置：
- HTML/JS/CSS → `no-cache, must-revalidate`（防 Cloudflare 缓存旧版）
- 视频/音频/图片 → `public, max-age=86400`

---

## 九、最新改动（本次会话完成的工作）

### 1. Profile 页面重构（已 commit + push 部署）

**改动**：
- 移除了"使用记录"区块（历史 Block 3）
- 在"可用总额"Credits 框内新增"查看详细使用记录 →"链接（指向 `/usage`）
- "今日使用"模块：只保留"视频识别"和"课程生成"两项，改为 2 列网格布局
- 新建 `frontend/usage.html`：独立使用记录详情页，支持加载更多（50条/批）

**关键文件**：
- `frontend/profile.html`：版本 `v=20260717c`
- `frontend/profile.js`：版本 `v=20260717c`，`renderCredits()` 里加了链接，`renderRateLimits()` 改为 2 列
- `frontend/usage.html`：全新页面，内联 JS，`/api/user/usage?limit=50&offset=N`
- `frontend/i18n.js`：新增 `profile.viewHistory` 键（6语言）
- `backend/commerce/usage_log.py`：`get_user_history()` 新增 `offset` 参数；新增 `get_user_history_count()`
- `backend/app.py`：`/api/user/usage` 支持 `limit`/`offset` 参数，响应新增 `total` 字段

### 2. Qwen3-ASR 集成（代码完成，API 访问受阻，待用户开通服务后可用）

**背景**：Qwen3-ASR 拥有词级时间戳（begin_time/end_time 毫秒精度），理论上优于 Whisper。

**已完成的代码**：
- `backend/ai/provider/qwen_asr.py`：完整实现
  - `transcribe_file(audio_path)` → `{segments, language, words}`
  - 流程：上传文件 → 提交异步任务 → 轮询 → 解析结果
  - 自动从 `dashscope://file-xxx` URL 格式取结果
- `backend/ai/speech.py`：新增 `transcribe_qwen()` + 在 `transcribe_video()` / `transcribe_slice()` 中添加 `elif provider == "qwen"` 分支
- `backend/config/providers.py`：新增 `class Qwen`（ASR_API_KEY/BASE_URL/UPLOAD_URL/ASR_MODEL）
- `backend/config/settings.py`：新增 `DASHSCOPE_API_KEY`/`DASHSCOPE_BASE_URL`/`DASHSCOPE_UPLOAD_URL`/`TIMEOUT_QWEN_ASR`
- `frontend/index.html`：`#transcribeProvider` 和 `#weEngine` 下拉框中新增 `qwen` 选项

**当前状态：API 访问受阻**

测试中发现此阿里云账号的 DashScope API Key（`sk-03788a014430454399dc013aa8433f33`）：
- 文件上传：✅ 成功（`dashscope://file-fe-xxx`）
- 异步转录 `/services/audio/asr/transcription`：❌ 403 "current user api does not support synchronous calls"（AccessDenied）
- 同步识别 `/services/audio/asr/recognition`：❌ 400 "url error"（实质也是未开通）
- OpenAI 兼容接口 `/audio/transcriptions`：❌ 404

**根因**：该 Key 来自「百炼（Bailian）控制台」，只有 LLM 推理权限。DashScope 语音识别是独立计费服务，需要在**阿里云主控制台**单独开通"智能语音交互"产品。

**要解决**：用户需在阿里云控制台开通语音识别服务，开通后现有代码可直接使用，无需修改。

---

## 十、当前未完成工作 / 待办

### Commerce Phase 3（最高优先级）

Phase 0（DB+Identity）✅、Phase 1（Wallet+Pricing+UsageLog）✅、Phase 2（Permission+Router）✅ 已完成。

**Phase 3 需要做的**：将现有 AI API 端点接入 CommerceContext 调用链。

每个端点的改法模板（以 `/api/transcribe` 为例）：

```python
@app.route("/api/transcribe", methods=["POST"])
def api_transcribe():
    db = get_db()
    uid = _get_user_id(db)
    plan = get_user_plan(db, uid)
    
    video = request.form.get("video")
    engine = request.form.get("engine", "groq")
    
    # 1. 估算输入规模
    duration = get_video_duration(os.path.join(VIDEOS_DIR, video))
    
    # 2. CommerceContext
    ctx = CommerceContext(db, uid, "transcription", "standard", plan)
    if not ctx.check_permission("CanTranscribe"):
        return jsonify({"error": "no permission"}), 403
    
    ctx.reserve({"duration_seconds": duration})  # 预扣 Credits
    
    try:
        result = transcribe_video(...)            # 实际 AI 调用
        ctx.settle({"duration_seconds": duration}, provider_id, model_id, latency_ms)
        return jsonify(result)
    except Exception as e:
        ctx.release_on_error(e)
        raise
```

需要接入的端点：
- `/api/transcribe`（转录）
- `/api/translate`（翻译）
- `/api/tts-generate`（TTS 合成）
- `/api/tts-content`（TTS 内容生成）
- `/api/pronounce`（发音评分）
- `/api/romanize`（拼音，但 zh 是本地免费）
- `/api/word-define`（单词释义）
- `/api/ocr`（图片文字）

### 其他待办

- [ ] Qwen3-ASR：等用户开通阿里云语音识别服务后测试（代码已写好）
- [ ] Railway 生产环境：需要新增 `DASHSCOPE_API_KEY`/`DASHSCOPE_BASE_URL`/`DASHSCOPE_UPLOAD_URL` 三个环境变量
- [ ] Phase 4：Admin API（查看所有用户用量、手动调整积分等）
- [ ] Phase 5：生产加固（cron 月度重置、reconcile 对账）
- [ ] 支付系统（Stripe/微信支付/支付宝）—— 计划中，尚未启动

---

## 十一、工作流规范

根据 `CLAUDE.md` 中的约定，AI 在完成改动后需要：

1. **语法检查**：`python -m py_compile backend/xxx.py` 或 `node --check frontend/xxx.js`
2. **本地测试**：后端接口改动后用 `curl` 实测（`python backend/app.py` 启动）
3. **自动 commit + push**：改动验证通过后，自动提交并推送 `origin main`（触发 Railway 自动部署）
4. **UI 改动**：无法自行验收时，明确告知用户需在浏览器/手机验收哪些点

---

## 十二、常见操作备查

### 本地运行

```bash
cd /Users/apple/Documents/videoplayer/backend
python app.py
# → http://localhost:5000
# → 手机局域网: http://192.168.1.3:5000
```

### 推送部署

```bash
cd /Users/apple/Documents/videoplayer
git add -p                 # 选择性暂存
git commit -m "feat: ..."
git push origin main       # Railway 自动部署
```

### 运行测试

```bash
cd /Users/apple/Documents/videoplayer/backend
python -m pytest tests/ -v
```

### 查看生产日志

```bash
# Railway 控制台搜索 [USAGE]
# 或本地 Admin API：
curl "https://getreelspeak.com/api/admin/logs?key=_tOZyw8avIRXRLaTWamzQA"
```

### 检查 i18n 版本号

当前：`?v=20260717c`。改动 i18n.js 后需同步更新以下文件的版本号：
- `frontend/index.html`
- `frontend/landing.html`
- `frontend/profile.html`
- `frontend/usage.html`

---

## 十三、AI 服务商能力速查

| Provider | 用途 | 优势 | 限制 |
|---------|------|-----|------|
| Groq | 转录（Whisper v3）| 快、便宜 | 句级时间戳，无词级 |
| OpenAI | 转录（Whisper-1）| 稳定 | 较贵 |
| Azure | 转录 + TTS + 发音评分 | 词级时间戳、发音评分唯一 | 按分钟计费较贵 |
| combined | 转录 | Groq 断句 + Azure 校准文本，双重计费 | 两次 API 调用 |
| Gemini | 翻译/TTS/OCR/图像生成 | 多模态，便宜 | 配额限制 |
| DeepSeek | 翻译/单词释义 | 便宜 | 中文语境最佳 |
| Qwen3-ASR | 转录 | 词级时间戳（毫秒），52种语言 | ★ 需开通阿里云 ASR 服务 |
| Cloudflare AI | 图像生成（FLUX） | 快速 | 分辨率有限 |
| Youdao | TTS（声音克隆）| 中文声音克隆 | 通过 Gradio API，不稳定 |

---

## 十四、最近 git 提交记录

```
63357d8 fix: use workspace-specific DashScope endpoint from env vars
7f82abf feat: add Qwen3-ASR (DashScope) as ASR provider option
a1d35ef Profile: remove history section, add usage page, 2-col rate grid
ae83299 fix: 更新三个页面的 i18n.js 版本号，强制刷新浏览器缓存
1dee031 fix: 今日使用改从 DB 查询 + 使用记录折叠显示
4b38f9a fix: 邀请卡片始终可见，移除依赖 API 成功才显示的设计缺陷
2d988b7 i18n: 邀请返利卡片补全 6 语言文案
457bdd8 fix: referral bind_referral FK 异常处理 + 77 项测试
694fd22 feat: 邀请返利系统完整实现
3126f6e feat: migrate domain to getreelspeak.com
```

---

## 十五、给接手 AI 的建议

**优先阅读顺序**：
1. 本文档（HANDOVER.md）
2. `ARCHITECTURE.md`（调用链、层间规则）
3. `CLAUDE.md`（产品规格、技术约束）
4. `backend/commerce/schema.sql`（数据库结构）
5. `backend/app.py` 头部 100 行（初始化、路由结构）

**最需要注意的约束**：
1. 前端**永远不引入框架**（这是产品约束，适配 2015 老 Mac）
2. 所有 `os.getenv()` 必须通过 `config/settings.py`（不可绕过）
3. 禁止用 `print()`，统一用 `get_logger(__name__)`
4. 改动前端文案必须同步 `i18n.js` 全部 6 语言 + 更新版本号
5. `player.js` 所有顶层执行语句必须在文件最底部

**最需要继续的工作**：
Commerce Phase 3 —— 把现有 AI 端点接入 CommerceContext 调用链，让计费真正生效。参考第十节的代码模板。

---

*文档完整覆盖截至 2026-07-17 的全部项目状态。*
