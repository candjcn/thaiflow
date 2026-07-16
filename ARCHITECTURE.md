# ReelSpeak — 技术架构文档
**版本**: v1.1 | **最后更新**: 2026-07-16
**变更说明**: v1.1 修订了 Commerce 调用链（Wallet.Confirm 替代 Wallet.Settle，Cost Engine 改为离线）

> 阅读本文前请先阅读 VISION.md 了解产品原则。
> 实施细节和任务拆分见 docs/commerce-platform-audit.md。

---

## 一、整体分层结构

```
┌─────────────────────────────────────────────────────┐
│              Frontend（纯原生 HTML/CSS/JS）           │
│   index.html  player.js  i18n.js  style.css         │
│   modules/（ES Modules，渐进式拆分）                  │
└───────────────────────┬─────────────────────────────┘
                        │ HTTP / SSE
┌───────────────────────▼─────────────────────────────┐
│              app.py（Flask 路由唯一入口）              │
│   只做路由分发和请求/响应处理，不含业务逻辑            │
└──┬──────────┬──────────┬──────────┬─────────────────┘
   │          │          │          │
   ▼          ▼          ▼          ▼
config/    ai/        domain/    commerce/
（配置）   （AI能力）  （领域模型） （计费平台）
```

---

## 二、后端目录结构

```
backend/
├── app.py                  # Flask 路由（唯一入口）
│
├── config/                 # 配置层（唯一入口，不可绕过）
│   ├── __init__.py         # 导出 settings, providers, get_logger
│   ├── settings.py         # 所有 os.getenv() 调用集中在此
│   ├── providers.py        # Provider Base URL、模型名、声音表
│   └── logger.py           # 统一日志工厂
│
├── ai/                     # AI 能力层（按能力划分，不按 Provider）
│   ├── speech.py           # 语音识别（transcription）
│   ├── translation.py      # 翻译 + 单词释义
│   ├── tts.py              # TTS 课程生成
│   ├── pronunciation.py    # 发音评估
│   └── provider/           # Provider 适配层（只被 ai/ 层调用）
│       ├── groq.py
│       ├── openai_whisper.py
│       ├── azure.py
│       ├── gemini.py       # 统一 Gemini HTTP 入口（request()）
│       ├── deepseek.py
│       ├── youdao.py
│       └── cloudflare.py
│
├── domain/                 # 领域模型（纯数据，无 IO）
│   ├── segment.py          # Segment（字幕分句）
│   ├── subtitle.py         # SubtitleFile
│   ├── tts_script.py       # TtsScript
│   ├── word.py             # Word
│   ├── definition.py       # Definition
│   └── pronunciation.py    # PronunciationResult
│
├── commerce/               # AI Commerce Platform
│   ├── __init__.py         # 导出 get_db, CommerceContext
│   ├── db.py               # init_db, get_db
│   ├── schema.sql          # DDL
│   ├── seed.py             # 初始数据（plan/costs/policies）
│   ├── identity.py         # 用户身份
│   ├── wallet.py           # Credits 账本
│   ├── pricing.py          # Capability → Credits 估算
│   ├── usage_log.py        # AI 调用结构化记录
│   ├── permission.py       # 权限引擎
│   ├── router.py           # AI Provider 路由
│   ├── cost_engine.py      # 离线成本核算（运营分析用）
│   └── middleware.py       # CommerceContext（调用链编排）
│
├── tests/                  # 单元测试（pytest）
│   ├── test_wallet.py
│   ├── test_pricing.py
│   ├── test_permission.py
│   ├── test_router.py
│   └── test_usage_log.py
│
├── export.py               # SRT / 带字幕视频导出
├── romanize.py             # 拼音 / 罗马拼音
└── r2.py                   # Cloudflare R2 上传
```

---

## 三、层间调用规则

```
允许的调用方向：
  app.py       → config/, ai/, commerce/, domain/, export.py, romanize.py, r2.py
  commerce/    → config/
  ai/          → config/, ai/provider/, domain/
  domain/      → （无外部依赖）

禁止的调用方向：
  ai/          → commerce/     （AI 层不知道 Billing 的存在）
  domain/      → 任何其他层
  commerce/    → ai/provider/  （Commerce 层不直接调用 Provider）
  app.py       → ai/provider/  （app.py 不绕过 ai/ 层直接调 Provider）
```

---

## 四、Capability → Provider 映射

| Capability | 主路由 | 主 Provider | Fallback | 计费单位 |
|-----------|--------|------------|---------|---------|
| transcription | /api/transcribe | groq | openai / azure | per_minute |
| retranscription | /api/retranscribe | groq | azure / gemini | per_minute |
| translation | /api/translate | deepseek | gemini（已有自动降级）| per_1k_chars |
| word_definition | /api/word-define | deepseek | — | per_request (fixed) |
| content_gen | /api/tts-content | gemini | deepseek | per_1k_tokens |
| tts_synthesis | /api/tts-generate | gemini | azure / youdao | per_1k_chars |
| pronunciation | /api/pronounce | azure | —（唯一）| per_minute |
| romanize_zh | /api/romanize | pypinyin（本地）| — | 免费（0 Credits）|
| romanize_th | /api/romanize | gemini | — | per_1k_chars |
| ocr | /api/ocr | gemini | — | per_image (fixed) |
| export | /api/export / /api/export-srt | ffmpeg（本地）| — | 免费（0 Credits）|

**Combined 转录**（groq 断句 + azure 校准）：两次 Provider 调用，记录两条 Usage Log，Credits 合并预扣。

---

## 五、AI Commerce Platform

### 5.1 七大模块

```
① AI Router         输入 Capability + Quality + Plan → 输出 ProviderHandle
② Identity          用户 / Profile / 登录绑定的唯一事实来源
③ Wallet            所有 Credits 的统一账本
④ Pricing Engine    Capability × Policy → Credits 估算（不认识 Provider）
⑤ Usage Log         每次 AI 调用的结构化记录（记录 actual_units 供离线分析）
⑥ Subscription      套餐定义（Free / Plus / Pro / Enterprise）
⑦ Permission Engine 命名权限集合，消除 if VIP
```

**Cost Engine**（第八个，独立于上述七个）：离线读取 Usage Log，计算真实 API 成本，用于运营分析，不影响用户账户。

### 5.2 调用链（已确定版本，v1.1 修订）

```
HTTP Request
  │
  ▼
Identity                  解析 user_id（当前过渡期：user_id = "anonymous"）
  │
  ▼
Permission Engine         check(user_id, "CanTranscribe") → 403 if denied
  │
  ▼
Pricing Engine.Estimate   estimate_credits(capability, quality, plan, input_metadata)
  │                       → estimate = 15 credits（含 10% buffer）
  ▼
Wallet.Reserve            reserve(user_id, estimate) → reservation_id
  │                       → 预扣 15 credits（subscription 优先）
  │                       → InsufficientFundsError → 402
  ▼
AI Router                 route(capability, quality, plan, preferred_provider)
  │                       → ProviderHandle{groq, whisper-large-v3, timeout=60}
  ▼
Provider Layer            execute(handle, input)
  │                       → on success: response + actual_units{duration_seconds: 142}
  │                       → on failure: Wallet.Release(reservation_id) → raise
  ▼
Usage Log.Record          record(user_id, capability, provider_id,
  │                              actual_units, latency_ms, status,
  │                              reservation_id, credits_reserved=15)
  ▼
Wallet.Confirm            confirm(reservation_id)
  │                       → 将 reserved 状态标记为 consumed
  │                       → 不重新计算 credits（用 estimate 作为最终扣款）
  ▼
Response → User           {result, credits_used: 15, balance_remaining: 635}

─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ 以下为离线处理 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─

[Background / Cost Engine]
  读 Usage Log 的 actual_units
  → 计算真实 API 成本（$0.0000237）
  → 用于运营成本报表、Provider 选择优化
  → 若 estimate 与 actual 偏差 > 20%，记录异常并优化估算参数
  → 不自动调整用户 Credits
```

### 5.3 为什么 Wallet 用 Confirm 而不是 Settle(actual)

**旧设计问题**（Pricing.Calculate → Wallet.Settle）：

1. SSE 长流（/api/transcribe 可能跑 30 秒）内存在开放的 billing 事务
2. Fallback 时（Groq 超时 → Azure 接替），哪个 Provider 的 actual_units 用于 Calculate？逻辑复杂
3. Provider Adapter 必须返回 `ActualUsage` 结构，增加每个 Provider 的实现负担
4. SSE 流失败时，Reserve 和 Settle 中间状态难以清理

**新设计原则**：

- **Billing 在调用前完成**：Reserve(estimate) 是唯一影响用户余额的操作
- **Usage Log 记录 actual**：actual_units 进 Usage Log，供离线分析，不影响实时计费
- **Cost Engine 是分析工具**：计算运营成本、发现估算偏差，不回写用户账户
- **Provider 的职责简化**：只需执行 AI 调用并返回结果，不需要汇报 ActualUsage 给 Billing

### 5.4 Wallet 方法集（最终版）

```python
reserve(user_id, amount) → reservation_id   # 预扣款
confirm(reservation_id)  → None             # 消费确认（不重算）
release(reservation_id)  → None             # AI失败时全额释放
add(user_id, amount, credit_type, ...)      # 充值（subscription/gift/paid）
refund(usage_log_id, amount, reason)        # 退款到 gift_credits（30天有效）
get_balance(user_id)     → dict             # 查询余额
get_history(user_id)     → list             # 流水记录
```

### 5.5 数据存储分工

| 数据域 | 存储方式 | 理由 |
|--------|---------|------|
| 视频文件 | 本地文件系统（Railway 临时）| 视频不持久化（方案 C）|
| 字幕 JSON | 本地 `videos/*.json` | 识别后下载到本地 |
| TTS 音频 | Cloudflare R2 | 需要持久化 URL |
| Commerce 数据 | SQLite（开发）/ PostgreSQL（生产）| 需要事务和并发控制 |

**为什么 Commerce 必须用 SQLite 而不是 JSON**：
- `Wallet.Reserve` 需要乐观锁（`version` 字段）防止并发双重扣款
- JSON 文件无法原子的 read-modify-write
- Usage Log 需要按用户/日期查询，JSON full-scan 无法接受

**为什么视频/字幕 JSON 不迁移到 SQLite**：
- 当前工作流够用，无并发修改需求
- 迁移收益 < 成本，等真正多用户同步场景再评估

---

## 六、前端架构

### 6.1 技术选型（硬性规定）

- 纯原生 HTML / CSS / JavaScript，禁止引入任何框架和构建工具
- 模块化机制：浏览器原生 ES Modules（`<script type="module">`）
- 状态管理：`frontend/modules/state.js` 单一数据源，禁止引入 Zustand 等状态库

### 6.2 当前文件结构

```
frontend/
├── index.html        # 播放器（/app 路由）
├── landing.html      # 首页
├── player.js         # 播放器主逻辑（渐进式模块化中）
├── i18n.js           # 国际化（6 语言）
├── style.css         # 全局样式
└── modules/
    └── state.js      # 共享状态（单一数据源）
```

### 6.3 player.js 渐进式模块化路线

**原则**：触机而动。修改某功能时顺手拆出，不主动重构。

```
Phase 0  已完成   消除 TDZ：初始化代码统一移到文件最底部
Phase 1  触机而动  lesson-db.js / favorites.js / export.js（依赖少）
Phase 2  触机而动  tts.js / pronunciation.js（中等复杂度）
Phase 3  触机而动  subtitles.js / player-core.js / playback-modes.js（核心，最后拆）
```

**TDZ 防护规则**（已生效）：`player.js` 中所有顶层执行语句必须在文件末尾 `// ========== 启动初始化 ==========` 区块内，在所有 `let`/`const` 声明之后。

---

## 七、测试策略

| 层级 | 工具 | 当前状态 | 覆盖范围 |
|------|------|---------|---------|
| Commerce 单元测试 | pytest | **现在就引入** | Wallet 并发、Pricing 公式、Permission 映射、Router 选择 |
| API 集成测试 | curl / httpie | 手动 | 后端接口改动后本地实测 |
| 前端回归 | 手动 checklist | 手动 | UI 改动后浏览器+手机验收 |
| E2E 测试 | Playwright | **延后** | 等产品稳定后再引入 |

**为什么 pytest 现在就要**：

`Wallet.Reserve` 的乐观锁逻辑、`Pricing.Estimate` 的 Credits 计算、`Permission.check` 的套餐映射——这些是计费核心，错误静默发生（没有崩溃，只是账目不对）。没有单元测试，无法验证它们在边界条件下的正确性。

---

## 八、Flask Blueprint 决策

**当前不引入 Blueprint。**

`app.py`（当前 1340 行）接入 Commerce 后预计增加约 200-300 行，但路由本身会变薄（逻辑全移到 `CommerceContext`）。Blueprint 是组织手段，不是边界手段，当前不是瓶颈。

**触发条件**：`app.py` 突破 2000 行 **且** 路由逻辑本身难以导航时，再引入 Blueprint，一步可达。

---

## 九、Provider 与 Billing 解耦验证

以下场景验证解耦正确性。任何实现不能破坏这些不变量：

```
场景 A：Groq 涨价
  操作：只改 provider_costs 表的 groq 单价
  影响：Cost Engine 分析数据变化；用户 Credits 扣款（基于 estimate）不变
  不影响：Wallet / Subscription / Permission / Usage Log 结构

场景 B：翻译从 DeepSeek 换到 Gemini
  操作：只改 AI Router 的路由配置
  影响：Usage Log 的 provider_id 字段从 "deepseek" 变为 "gemini"
  不影响：Wallet 扣款金额、Pricing Policy、用户感知

场景 C：新增 Provider（如 Anthropic Claude）
  操作：
    1. 在 ai/provider/ 新增 anthropic.py
    2. 在 provider_costs 表插入成本记录
    3. 在 router.py 路由配置中加入
  不需要改：Wallet / Pricing / Subscription / Permission / Usage Log 结构

场景 D：下线 Provider
  操作：AI Router 中将其 Health Score 设为 0（永不选中）
  不需要改：任何其他模块
  历史 Usage Log 保留（记录了历史事实）
```
