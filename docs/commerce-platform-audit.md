# AI Commerce Platform — 项目扫描报告 & 任务拆分
**日期**: 2026-07-16 | **基于**: 架构设计 v1.0 + 完整代码扫描

---

## 一、项目现状扫描结果

### 1.1 现有 Provider 层（ai/provider/）

| Provider | 文件 | 支持能力 | 计费单位 | 估算单价 |
|----------|------|---------|---------|---------|
| Groq | groq.py | ASR（Whisper Large v3） | per_minute | ~$0.0001/min |
| OpenAI | openai_whisper.py | ASR（Whisper-1） | per_minute | ~$0.0006/min |
| Azure | azure.py | ASR + TTS + Pronunciation | per_minute / per_char | ASR $0.0004/min, TTS $0.016/1k chars |
| Gemini | gemini.py | Translation + TTS + OCR + Romanize + Content | per_token | ~$0.000075/1k input tokens |
| DeepSeek | deepseek.py | Translation + WordDefine + ContentGen | per_token | ~$0.14/1M input tokens |
| Youdao | youdao.py | TTS（声音克隆） | per_char | 待确认 |
| Cloudflare | cloudflare.py | Image generation（FLUX） | per_image | ~$0.003/image |

### 1.2 现有 Capability 映射（路由 → 能力 → Provider）

```
/api/transcribe          → transcription    → groq (default) | openai | azure | combined(groq+azure)
/api/retranscribe        → retranscription  → groq | azure | gemini（单句重识别）
/api/retranscribe-audio  → retranscription  → groq | azure | gemini（单句录音识别）
/api/translate           → translation      → deepseek → gemini（已有fallback！）
/api/word-define         → word_definition  → deepseek
/api/tts-content         → content_gen      → deepseek(zh) | gemini(其他语言)
/api/tts-generate        → tts_synthesis    → gemini | azure | youdao
/api/romanize            → romanize         → pypinyin(zh,本地免费) | gemini(th)
/api/romanize-batch      → romanize         → 同上（批量版）
/api/ocr                 → ocr              → gemini
/api/pronounce           → pronunciation    → azure（仅此一家）
/api/export-srt          → export           → 无AI，本地ffmpeg（免费）
/api/export              → export_video     → 无AI，本地ffmpeg（免费）
/api/bookmark-sentence   → bookmark         → R2 存储（非AI计费）
/api/bookmark-audio      → bookmark         → R2 存储（非AI计费）
```

### 1.3 已有的 Fallback 机制（部分）

```python
# ai/translation.py 第71-81行：已实现 DeepSeek → Gemini 自动降级
try:
    content = deepseek_provider.chat(prompt, ...)
    provider = "deepseek"
except Exception:
    logger.warning("DeepSeek 失败，降级到 Gemini")
    content = _call_gemini(...)
    provider = "gemini"
```

**结论**：翻译 Fallback 已存在但是分散在业务代码中。Router 需要把这个模式提升为统一机制。

### 1.4 现有 Usage Log（log_event）分析

**现有记录字段**（app.py，log_event 调用汇总）：

| 事件 | 记录字段 | 缺失字段 |
|------|---------|---------|
| transcribe | video, provider, language, segments | duration_sec, latency_ms, cost_usd, credits, user_id |
| retranscribe | video, provider, language, word | duration_sec, latency_ms |
| tts_generate | engine, language, chars | latency_ms, cost_usd, credits |
| tts_content_gen | language, prompt_len | latency_ms, cost_usd |
| ocr | language, chars | latency_ms, cost_usd |
| bookmark | video, range | — |

**现有格式**（JSONL 文件 videos/usage_log.jsonl）：
```json
{"time": "2026-07-16 10:23:01", "event": "transcribe", "video": "test.mp4", "provider": "groq", "language": "th", "segments": 42}
```

**问题**：缺少用户身份（无认证）、无成本追踪、无延迟记录、无 request_id 关联。

### 1.5 "Combined" 转录模式的特殊性

`combined` 模式 = Groq（断句）+ Azure（文字校准），实际使用了两个 Provider。
这在 AI Router 中需要特殊处理：一次 Capability Request 可能触发两次 Provider 调用。

建议：定义 `CompositeProvider` 类型，拆分为两次独立的 UsageLog 记录。

### 1.6 免费 Capability 识别

以下 Capability 不产生 AI API 成本：
- `romanize`（中文）→ pypinyin 本地计算，永远免费
- `export_srt` → 纯本地 ffmpeg
- `export_video` → 纯本地 ffmpeg（但耗 CPU/时间）
- `bookmark` → R2 存储（有存储成本，但非 AI 成本）

建议：Pricing Engine 对这些设置 `formula=fixed, amount=0`，仍走计费链路但扣 0 Credits，保留 Usage Log。

---

## 二、架构设计 Review（对比实际代码）

### 2.1 设计与现实完全吻合 ✅

- Provider 层抽象已存在（ai/provider/ 目录结构正确）
- Capability 边界清晰（ai/speech.py, ai/translation.py 等已按能力分离）
- 配置集中（config/settings.py + providers.py 已统一管理）
- Gemini 调用已有统一入口（gemini_provider.request()）

### 2.2 需要调整的设计细节

#### 调整1：TTS 拆分为两个子能力

原设计只有 `tts`，实际上有两个截然不同的 API 调用：

```
tts_content_gen  → AI 生成双语文本（Gemini/DeepSeek）  计费：per_token
tts_synthesis    → 文本转语音文件（Gemini/Azure/Youdao）  计费：per_char
```

建议：CapabilityType 中增加 `content_gen`，`tts` 仅指 `tts_synthesis`。

#### 调整2：Romanize 分段计费

```
romanize_zh  → pypinyin 本地，Credits = 0
romanize_th  → Gemini API，Credits > 0
```

建议：Pricing Engine 中 romanize 按语言子类型定价（language metadata 传入）。

#### 调整3：Combined 转录的 Router 处理

```
combined = groq.transcribe() + azure.transcribe()
```

Router 路由结果：返回 `CompositeProviderHandle[groq, azure]`，UsageLog 记录两条，Credits 合并扣除。

#### 调整4：Pronunciation 无 Fallback

Azure 是唯一发音评分 Provider，暂无 Fallback。
设计时标注 `no_fallback=true`，失败直接报错给用户。

#### 调整5：初期 Identity 可用 ADMIN_KEY 替代

当前无认证，可用 `ADMIN_KEY` 作为管理员身份、匿名用户统一用 `user_id="anonymous"` 作为过渡。

### 2.3 数据库选型

- **开发阶段**：SQLite（backend/commerce.db，gitignore）
- **生产阶段**：Railway 提供的 PostgreSQL（后续 migration）
- **无 ORM**：遵循 CLAUDE.md 设计克制原则，用原生 SQL + sqlite3/psycopg2

---

## 三、完整任务拆分（含测试用例）

> 原则：每个 Task 独立可测，完成后平台能正常运行，不破坏现有 API 契约。

---

### PHASE 0：数据基础

---

#### Task 0.1：数据库 Schema 设计与初始化
**文件**：`backend/commerce/db.py`, `backend/commerce/schema.sql`  
**优先级**：P0 | **前置**：无

**实现内容**：
```sql
-- 用户表
CREATE TABLE users (
    user_id     TEXT PRIMARY KEY,   -- UUID
    email       TEXT UNIQUE,
    status      TEXT DEFAULT 'active',  -- active/suspended/deleted
    created_at  TEXT DEFAULT (datetime('now'))
);

-- 套餐定义（运营配置，代码中读取）
CREATE TABLE plan_definitions (
    plan_id         TEXT PRIMARY KEY,  -- free/plus/pro/enterprise
    display_name    TEXT,
    monthly_credits INTEGER DEFAULT 0,
    features_json   TEXT,              -- JSON: capabilities, permissions, quality_tiers, etc.
    effective_from  TEXT
);

-- 用户订阅
CREATE TABLE user_subscriptions (
    sub_id         TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    plan_id        TEXT NOT NULL,
    status         TEXT DEFAULT 'active',  -- active/expired/cancelled
    started_at     TEXT,
    expires_at     TEXT,
    credits_quota  INTEGER DEFAULT 0,
    credits_reset_at TEXT,
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);

-- Wallet
CREATE TABLE wallets (
    wallet_id             TEXT PRIMARY KEY,
    user_id               TEXT UNIQUE NOT NULL,
    subscription_credits  INTEGER DEFAULT 0,
    subscription_expires_at TEXT,
    gift_credits          INTEGER DEFAULT 0,
    paid_credits          INTEGER DEFAULT 0,
    version               INTEGER DEFAULT 0,  -- 乐观锁
    updated_at            TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);

-- Wallet 流水
CREATE TABLE wallet_transactions (
    tx_id        TEXT PRIMARY KEY,
    wallet_id    TEXT NOT NULL,
    tx_type      TEXT,    -- reserve/settle/release/add/refund
    amount       INTEGER, -- 正=入账，负=扣除
    credit_type  TEXT,    -- subscription/gift/paid
    ref_id       TEXT,    -- usage_log_id 或 order_id
    note         TEXT,
    created_at   TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(wallet_id) REFERENCES wallets(wallet_id)
);

-- Provider 成本表（运营维护）
CREATE TABLE provider_costs (
    cost_id     TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,  -- groq/azure/gemini/deepseek/youdao
    model_id    TEXT NOT NULL,
    capability  TEXT NOT NULL,  -- transcription/translation/tts/...
    unit        TEXT NOT NULL,  -- per_minute/per_1k_chars/per_1k_tokens/per_image
    unit_price  REAL NOT NULL,  -- USD
    updated_at  TEXT DEFAULT (datetime('now'))
);

-- 定价策略（运营维护）
CREATE TABLE pricing_policies (
    policy_id      TEXT PRIMARY KEY,
    capability     TEXT NOT NULL,
    quality_tier   TEXT DEFAULT 'standard',  -- economy/standard/premium
    plan_id        TEXT DEFAULT 'all',
    formula        TEXT DEFAULT 'cost_multiplier',  -- fixed/cost_multiplier/tiered
    multiplier     REAL DEFAULT 3.0,
    fixed_amount   INTEGER DEFAULT 0,
    min_credits    INTEGER DEFAULT 1,
    max_credits    INTEGER DEFAULT 9999,
    effective_from TEXT,
    effective_to   TEXT
);

-- Usage Log v2
CREATE TABLE usage_logs (
    log_id             TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL,
    capability         TEXT NOT NULL,
    quality_tier       TEXT DEFAULT 'standard',
    provider_id        TEXT,
    model_id           TEXT,
    plan_id            TEXT,
    input_units        REAL,
    input_unit_type    TEXT,  -- seconds/chars/tokens/images
    provider_cost_usd  REAL,
    credits_reserved   INTEGER DEFAULT 0,
    credits_charged    INTEGER DEFAULT 0,
    credits_refunded   INTEGER DEFAULT 0,
    latency_ms         INTEGER,
    status             TEXT DEFAULT 'success',  -- success/failed/refunded/timeout
    error_code         TEXT,
    retry_count        INTEGER DEFAULT 0,
    fallback_used      INTEGER DEFAULT 0,
    fallback_from      TEXT,
    requested_at       TEXT DEFAULT (datetime('now')),
    completed_at       TEXT,
    reservation_id     TEXT,
    request_id         TEXT,
    extra_json         TEXT   -- 额外元数据（如 video_name, language）
);

-- Permission grants（手动授权）
CREATE TABLE permission_grants (
    grant_id    TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    permission  TEXT NOT NULL,  -- CanTranscribe/CanTTS/...
    granted_by  TEXT,
    expires_at  TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_usage_logs_user ON usage_logs(user_id, requested_at);
CREATE INDEX idx_wallet_tx_wallet ON wallet_transactions(wallet_id, created_at);
```

**测试用例**：
```python
# test_commerce_db.py

def test_schema_creates_all_tables():
    """所有表能正常创建"""
    db = init_db(":memory:")
    tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = [t[0] for t in tables]
    assert "users" in names
    assert "wallets" in names
    assert "usage_logs" in names
    assert "pricing_policies" in names

def test_schema_unique_wallet_per_user():
    """每个用户只能有一个 wallet"""
    db = init_db(":memory:")
    create_user(db, "u1")
    create_wallet(db, "u1")
    with pytest.raises(Exception):  # UNIQUE constraint
        create_wallet(db, "u1")
```

---

#### Task 0.2：Identity 模块
**文件**：`backend/commerce/identity.py`  
**优先级**：P0 | **前置**：Task 0.1

**实现内容**：
```python
def create_user(db, email=None) -> str:  # 返回 user_id
def get_user(db, user_id: str) -> dict | None
def get_user_plan(db, user_id: str) -> str  # 返回 plan_id，默认 "free"
def get_or_create_anonymous(db) -> str  # 返回固定 anonymous user_id
def set_user_subscription(db, user_id, plan_id, expires_at, credits_quota)
```

**过渡方案**：所有无认证请求使用 `user_id = "anonymous"`，在 Phase 3 集成时替换为真实 JWT 用户 ID。

**测试用例**：
```python
def test_create_user_returns_uuid():
    db = init_db(":memory:")
    uid = create_user(db)
    assert len(uid) == 36  # UUID格式

def test_get_user_plan_default_free():
    db = init_db(":memory:")
    uid = create_user(db)
    assert get_user_plan(db, uid) == "free"

def test_get_or_create_anonymous_idempotent():
    db = init_db(":memory:")
    id1 = get_or_create_anonymous(db)
    id2 = get_or_create_anonymous(db)
    assert id1 == id2  # 幂等
```

---

#### Task 0.3：Seed 初始化数据
**文件**：`backend/commerce/seed.py`  
**优先级**：P0 | **前置**：Task 0.1

**实现内容**：插入 plan_definitions + provider_costs + pricing_policies 初始数据。

**Provider 成本初始值**（基于市场公开价格）：
```python
PROVIDER_COSTS = [
    # provider_id, model_id, capability, unit, unit_price_usd
    ("groq", "whisper-large-v3", "transcription", "per_minute", 0.0001),
    ("openai", "whisper-1", "transcription", "per_minute", 0.006),
    ("azure", "azure-speech", "transcription", "per_minute", 0.0004),
    ("azure", "azure-speech", "pronunciation", "per_minute", 0.0004),
    ("azure", "azure-tts-neural", "tts", "per_1k_chars", 0.016),
    ("gemini", "gemini-3.1-flash-lite", "translation", "per_1k_tokens", 0.00015),
    ("gemini", "gemini-3.1-flash-lite", "content_gen", "per_1k_tokens", 0.00015),
    ("gemini", "gemini-3.1-flash-lite", "romanize", "per_1k_tokens", 0.00015),
    ("gemini", "gemini-3.1-flash-lite", "ocr", "per_image", 0.002),
    ("gemini", "gemini-3.1-flash-tts", "tts", "per_1k_chars", 0.005),
    ("deepseek", "deepseek-chat", "translation", "per_1k_tokens", 0.00014),
    ("deepseek", "deepseek-chat", "word_definition", "per_request", 0.001),
    ("deepseek", "deepseek-chat", "content_gen", "per_1k_tokens", 0.00014),
    ("youdao", "youdao-tts", "tts", "per_1k_chars", 0.01),
    ("cloudflare", "flux-1-schnell", "image_gen", "per_image", 0.003),
]

# 套餐定义
PLAN_DEFINITIONS = {
    "free": {
        "display_name": "免费版",
        "monthly_credits": 100,
        "capabilities": ["transcription", "translation"],
        "permissions": ["CanTranscribe", "CanTranslate"],
        "quality_tiers": ["economy"],
        "max_file_duration_min": 5,
    },
    "plus": {
        "display_name": "Plus 会员",
        "monthly_credits": 1000,
        "capabilities": ["transcription", "translation", "tts", "romanize", "word_definition", "export"],
        "permissions": ["CanTranscribe", "CanTranslate", "CanTTS", "CanRomanize", "CanWordDefine", "CanExport"],
        "quality_tiers": ["economy", "standard"],
        "max_file_duration_min": 30,
    },
    "pro": {
        "display_name": "Pro 会员",
        "monthly_credits": 5000,
        "capabilities": ["ALL"],
        "permissions": ["ALL"],
        "quality_tiers": ["economy", "standard", "premium"],
        "max_file_duration_min": 120,
    },
    "enterprise": {
        "display_name": "企业版",
        "monthly_credits": 50000,
        "capabilities": ["ALL"],
        "permissions": ["ALL"],
        "quality_tiers": ["ALL"],
        "max_file_duration_min": -1,  # unlimited
    },
}

# 定价策略（Credits = provider_cost × multiplier × exchange_rate）
PRICING_POLICIES = [
    # capability, quality_tier, plan_id, formula, multiplier, fixed_amount, min_credits
    ("transcription", "economy",  "all", "cost_multiplier", 2.0, 0, 1),
    ("transcription", "standard", "all", "cost_multiplier", 2.5, 0, 1),
    ("transcription", "premium",  "all", "cost_multiplier", 3.0, 0, 2),
    ("translation",   "standard", "all", "cost_multiplier", 2.0, 0, 1),
    ("tts",           "standard", "all", "cost_multiplier", 2.5, 0, 1),
    ("pronunciation", "standard", "all", "cost_multiplier", 2.0, 0, 1),
    ("romanize",      "standard", "all", "fixed",           1.0, 0, 0),  # 中文免费，泰语1 credit
    ("word_definition","standard","all", "fixed",           1.0, 1, 1),  # 固定1 credit/次
    ("content_gen",   "standard", "all", "cost_multiplier", 2.0, 0, 1),
    ("ocr",           "standard", "all", "fixed",           1.0, 2, 2),  # 固定2 credits/张
    ("export",        "standard", "all", "fixed",           1.0, 0, 0),  # 免费
    ("image_gen",     "standard", "all", "fixed",           1.0, 5, 5),  # 固定5 credits/张
]
```

**测试用例**：
```python
def test_seed_creates_4_plans():
    db = init_db(":memory:")
    run_seed(db)
    plans = db.execute("SELECT count(*) FROM plan_definitions").fetchone()[0]
    assert plans == 4

def test_seed_idempotent():
    db = init_db(":memory:")
    run_seed(db)
    run_seed(db)  # 重复执行不报错（INSERT OR REPLACE）
    plans = db.execute("SELECT count(*) FROM plan_definitions").fetchone()[0]
    assert plans == 4  # 不重复插入
```

---

### PHASE 1：核心计费链

---

#### Task 1.1：Wallet 模块
**文件**：`backend/commerce/wallet.py`  
**优先级**：P1 | **前置**：Task 0.1, 0.2

**实现内容**：
```python
class InsufficientFundsError(Exception): pass
class WalletNotFoundError(Exception): pass

def get_or_create_wallet(db, user_id: str) -> dict
def get_balance(db, user_id: str) -> dict  
    # → {"subscription": int, "gift": int, "paid": int, "total": int}

def reserve(db, user_id: str, amount: int) -> str  
    # 预扣款，返回 reservation_id
    # 消费优先级：subscription → gift → paid
    # 乐观锁：检查 version，失败重试最多3次
    # Raises: InsufficientFundsError

def settle(db, reservation_id: str, actual_amount: int) -> None
    # 用实际金额结算（可能 < 或 > reserved）
    # 差额自动退还或追加扣除

def release(db, reservation_id: str) -> None
    # AI 失败时全额释放预扣

def add_credits(db, user_id: str, amount: int, credit_type: str, source: str, expires_at=None) -> None
    # 充值：subscription/gift/paid

def refund(db, usage_log_id: str, amount: int, reason: str) -> None
    # 退款到 gift_credits（30天有效）

def get_history(db, user_id: str, limit=50) -> list[dict]
    # 流水记录
```

**测试用例**：
```python
def test_reserve_deducts_subscription_first():
    """消费顺序：先扣 subscription，再扣 gift，最后扣 paid"""
    db = setup_db_with_wallet(subscription=100, gift=50, paid=200)
    rid = reserve(db, "u1", 80)
    bal = get_balance(db, "u1")
    assert bal["subscription"] == 20  # 100-80
    assert bal["gift"] == 50          # 未动
    assert bal["paid"] == 200         # 未动

def test_reserve_crosses_credit_types():
    """跨类型消费：subscription 不够时自动用 gift"""
    db = setup_db_with_wallet(subscription=10, gift=50, paid=0)
    reserve(db, "u1", 30)
    bal = get_balance(db, "u1")
    assert bal["subscription"] == 0   # 全用完
    assert bal["gift"] == 30          # 50-20

def test_reserve_insufficient_raises():
    db = setup_db_with_wallet(subscription=5, gift=0, paid=0)
    with pytest.raises(InsufficientFundsError):
        reserve(db, "u1", 10)

def test_settle_less_than_reserved_refunds_diff():
    """实际用量少于预扣时，退还差额"""
    db = setup_db_with_wallet(subscription=100)
    rid = reserve(db, "u1", 20)
    settle(db, rid, 15)
    bal = get_balance(db, "u1")
    assert bal["subscription"] == 85  # 100-15（退回5）

def test_settle_more_than_reserved_deducts_extra():
    """实际用量多于预扣时，额外扣除"""
    db = setup_db_with_wallet(subscription=100)
    rid = reserve(db, "u1", 10)
    settle(db, rid, 12)
    bal = get_balance(db, "u1")
    assert bal["subscription"] == 88  # 100-12

def test_release_restores_balance():
    """AI 失败时释放预扣"""
    db = setup_db_with_wallet(subscription=100)
    rid = reserve(db, "u1", 30)
    release(db, rid)
    bal = get_balance(db, "u1")
    assert bal["subscription"] == 100  # 完全恢复

def test_concurrent_reserve_no_double_spend(tmp_path):
    """并发预扣不超发（乐观锁保证）"""
    db = setup_db_with_wallet(subscription=100)
    import threading
    results = []
    errors = []

    def try_reserve():
        try:
            results.append(reserve(db, "u1", 60))
        except InsufficientFundsError:
            errors.append("insufficient")

    threads = [threading.Thread(target=try_reserve) for _ in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()

    # 只有1次或2次能成功（60+60=120 > 100，至少1次失败）
    assert len(errors) >= 1
    bal = get_balance(db, "u1")
    assert bal["total"] >= 0  # 余额不能为负
```

---

#### Task 1.2：Pricing Engine
**文件**：`backend/commerce/pricing.py`  
**优先级**：P1 | **前置**：Task 0.1, 0.3

**实现内容**：
```python
# 汇率：USD → Credits（运营可调整）
USD_TO_CREDITS_RATE = 1000  # $1 = 1000 credits

def estimate_credits(db, capability: str, quality_tier: str, plan_id: str, 
                     input_metadata: dict) -> int:
    """调用前估算所需 Credits（带10%余量）"""

def calculate_credits(db, capability: str, quality_tier: str, plan_id: str,
                      provider_id: str, model_id: str, actual_usage: dict) -> tuple[int, float]:
    """AI返回后精确计算：返回 (credits, cost_usd)"""

# input_metadata / actual_usage 格式：
# transcription: {"duration_seconds": 142.3}
# translation:   {"char_count": 3200} 或 {"token_count": 800}
# tts:           {"char_count": 480}
# pronunciation: {"duration_seconds": 8.5}
# word_definition: {}  (fixed pricing)
# ocr:           {}    (fixed pricing)
# romanize_th:   {"char_count": 120}
# romanize_zh:   {}    (free, always 0)
```

**测试用例**：
```python
def test_estimate_transcription_groq():
    """Groq 转录142秒估算：0.0001/min × 142/60 × 2.5倍率 × 1000 rate ≈ 0.59 credits，最小值=1"""
    db = seeded_db()
    credits = estimate_credits(db, "transcription", "standard", "plus",
                               {"duration_seconds": 142.3})
    assert credits >= 1  # 最小1 credit

def test_calculate_credits_fixed():
    """word_definition固定1 credit"""
    db = seeded_db()
    credits, cost = calculate_credits(db, "word_definition", "standard", "plus",
                                      "deepseek", "deepseek-chat", {})
    assert credits == 1

def test_calculate_credits_free():
    """romanize_zh 免费（pypinyin本地）"""
    db = seeded_db()
    credits, cost = calculate_credits(db, "romanize", "standard", "plus",
                                      "local", "pypinyin", {})
    assert credits == 0
    assert cost == 0.0

def test_estimate_includes_buffer():
    """估算值应比精确值多约10%"""
    db = seeded_db()
    estimate = estimate_credits(db, "transcription", "standard", "plus",
                                {"duration_seconds": 300})
    exact, _ = calculate_credits(db, "transcription", "standard", "plus",
                                 "groq", "whisper-large-v3", {"duration_seconds": 300})
    assert estimate >= exact  # 估算值 >= 实际值

def test_pricing_policy_not_expose_provider():
    """Pricing Engine 只接受 capability，不接受 Provider 作为定价依据"""
    # 不管用 groq 还是 azure，同一 capability/quality_tier/plan 的 Credits 相同
    db = seeded_db()
    c_groq, _ = calculate_credits(db, "transcription", "economy", "plus",
                                   "groq", "whisper-large-v3", {"duration_seconds": 60})
    c_azure, _ = calculate_credits(db, "transcription", "economy", "plus",
                                    "azure", "azure-speech", {"duration_seconds": 60})
    assert c_groq == c_azure  # 用户眼中价格相同（Provider 对用户透明）
```

---

#### Task 1.3：Usage Log v2
**文件**：`backend/commerce/usage_log.py`  
**优先级**：P1 | **前置**：Task 0.1

**实现内容**：
```python
def record(db, *, 
           user_id, capability, quality_tier="standard",
           provider_id, model_id, plan_id,
           input_units, input_unit_type,
           provider_cost_usd,
           credits_reserved, credits_charged, credits_refunded=0,
           latency_ms, status="success",
           error_code=None, retry_count=0,
           fallback_used=False, fallback_from=None,
           requested_at, completed_at,
           reservation_id=None, request_id=None,
           extra=None) -> str:  # 返回 log_id

def get_user_history(db, user_id, limit=50) -> list[dict]
def get_log(db, log_id: str) -> dict | None
def get_summary(db, user_id: str, since_days=30) -> dict
    # → {"total_credits": int, "by_capability": {...}, "by_provider": {...}}

# 向后兼容：继续调用原有 log_event 同时写 usage_log（双写过渡）
```

**测试用例**：
```python
def test_record_returns_log_id():
    db = init_db(":memory:")
    log_id = record(db, user_id="u1", capability="transcription", ...)
    assert len(log_id) == 36

def test_record_can_be_retrieved():
    db = init_db(":memory:")
    log_id = record(db, user_id="u1", capability="translation", ...)
    log = get_log(db, log_id)
    assert log["capability"] == "translation"

def test_summary_aggregates_by_capability():
    db = init_db(":memory:")
    record(db, user_id="u1", capability="transcription", credits_charged=10, ...)
    record(db, user_id="u1", capability="translation", credits_charged=5, ...)
    record(db, user_id="u1", capability="transcription", credits_charged=8, ...)
    summary = get_summary(db, "u1")
    assert summary["by_capability"]["transcription"] == 18
    assert summary["by_capability"]["translation"] == 5
```

---

### PHASE 2：路由与权限

---

#### Task 2.1：Permission Engine
**文件**：`backend/commerce/permission.py`  
**优先级**：P2 | **前置**：Task 0.2, 0.3

**实现内容**：
```python
# 权限枚举
PERMISSIONS = {
    "CanTranscribe", "CanTranslate", "CanTTS", "CanTTSContent",
    "CanPronunciationAssess", "CanRomanize", "CanWordDefine",
    "CanExport", "CanOCR", "CanShadowing", "CanImageGen",
    "CanUseStandardQuality", "CanUsePremiumQuality",
    "CanProcessLongVideo",  # > 5 min
}

def check(db, user_id: str, permission: str) -> bool
def check_all(db, user_id: str, permissions: list) -> dict[str, bool]
def get_user_permissions(db, user_id: str) -> set[str]
def grant(db, user_id: str, permission: str, expires_at=None) -> None
def revoke(db, user_id: str, permission: str) -> None

# Plan → Permission 映射（从 plan_definitions.features_json 读取）
def _get_plan_permissions(db, plan_id: str) -> set[str]
```

**测试用例**：
```python
def test_free_user_can_transcribe():
    db = seeded_db()
    create_user_with_plan(db, "u1", "free")
    assert check(db, "u1", "CanTranscribe") == True

def test_free_user_cannot_tts():
    db = seeded_db()
    create_user_with_plan(db, "u1", "free")
    assert check(db, "u1", "CanTTS") == False

def test_plus_user_can_tts():
    db = seeded_db()
    create_user_with_plan(db, "u1", "plus")
    assert check(db, "u1", "CanTTS") == True

def test_manual_grant_overrides_plan():
    """手动授权可以超越套餐限制"""
    db = seeded_db()
    create_user_with_plan(db, "u1", "free")
    grant(db, "u1", "CanTTS", expires_at="2099-01-01")
    assert check(db, "u1", "CanTTS") == True

def test_revoke_removes_manual_grant():
    db = seeded_db()
    create_user_with_plan(db, "u1", "free")
    grant(db, "u1", "CanTTS")
    revoke(db, "u1", "CanTTS")
    assert check(db, "u1", "CanTTS") == False  # 回到套餐权限

def test_check_all_batch():
    db = seeded_db()
    create_user_with_plan(db, "u1", "plus")
    result = check_all(db, "u1", ["CanTranscribe", "CanTTS", "CanImageGen"])
    assert result["CanTranscribe"] == True
    assert result["CanTTS"] == True
    assert result["CanImageGen"] == False  # plus 没有 image_gen
```

---

#### Task 2.2：AI Router（静态路由版）
**文件**：`backend/commerce/router.py`  
**优先级**：P2 | **前置**：Task 0.3

**实现内容**：
```python
# ProviderHandle 数据类
@dataclass
class ProviderHandle:
    provider_id: str
    model_id: str
    capability: str
    timeout: int
    is_composite: bool = False
    sub_handles: list = field(default_factory=list)

def route(capability: str, quality_tier: str, plan_id: str,
          preferred_provider: str = None,  # 用户显式选择（兼容现有UI）
          input_metadata: dict = None) -> ProviderHandle:
    """选择 Provider。
    
    优先级：
    1. 用户显式指定 preferred_provider（兼容现有 API 参数）
    2. quality_tier + plan_id 路由规则
    3. 内置默认（最低成本）
    """

# 路由表（静态配置，Task 2.3 加入 Health Check 后变动态）
ROUTING_TABLE = {
    # capability → quality_tier → [primary, fallback1, fallback2]
    "transcription": {
        "economy":  ["groq", "azure"],
        "standard": ["groq", "azure"],
        "premium":  ["azure", "groq"],
    },
    "translation": {
        "economy":  ["deepseek", "gemini"],
        "standard": ["deepseek", "gemini"],
        "premium":  ["gemini", "deepseek"],
    },
    "tts": {
        "economy":  ["azure", "gemini"],
        "standard": ["gemini", "azure"],
        "premium":  ["gemini", "azure"],
    },
    "pronunciation": {
        "standard": ["azure"],  # 唯一选择
    },
    "romanize": {
        "standard": ["local", "gemini"],  # local=pypinyin（中文免费）
    },
    "word_definition": {
        "standard": ["deepseek", "gemini"],
    },
    "content_gen": {
        "standard": ["gemini", "deepseek"],
    },
    "ocr": {
        "standard": ["gemini"],
    },
}

def with_fallback(handle: ProviderHandle, error: Exception) -> ProviderHandle | None:
    """当前 Provider 失败时，返回下一个候选（无候选时返回 None）"""
```

**测试用例**：
```python
def test_route_transcription_default_is_groq():
    handle = route("transcription", "standard", "plus")
    assert handle.provider_id == "groq"

def test_route_respects_preferred_provider():
    """用户显式选择 azure 时必须路由到 azure"""
    handle = route("transcription", "standard", "plus", preferred_provider="azure")
    assert handle.provider_id == "azure"

def test_route_combined_returns_composite():
    """combined 模式返回 CompositeHandle"""
    handle = route("transcription", "standard", "plus", preferred_provider="combined")
    assert handle.is_composite == True
    assert len(handle.sub_handles) == 2

def test_with_fallback_returns_next_provider():
    handle = route("translation", "standard", "plus")  # deepseek
    fallback = with_fallback(handle, Exception("timeout"))
    assert fallback.provider_id == "gemini"

def test_with_fallback_no_more_returns_none():
    handle = route("pronunciation", "standard", "plus")  # azure（唯一）
    fallback = with_fallback(handle, Exception("error"))
    assert fallback is None  # 无 fallback

def test_route_provider_not_in_billing():
    """路由结果中的 provider_id 只用于选择 Provider，不影响 Pricing"""
    handle1 = route("translation", "standard", "plus")  # deepseek
    handle2 = route("translation", "standard", "plus", preferred_provider="gemini")
    # 两个 handle 路由到不同 provider，但 capability 相同
    # Pricing Engine 用 capability 定价，与 provider 无关
    from commerce.pricing import estimate_credits
    # 这里只验证路由不持有定价逻辑
    assert not hasattr(handle1, "credits")
    assert not hasattr(handle2, "credits")
```

---

#### Task 2.3：AI Router Health Check（可选，Phase 2 后期）
**文件**：`backend/commerce/health.py`  
**优先级**：P2（可选）| **前置**：Task 2.2

**实现内容**：
```python
# 后台线程定时 ping Provider
# 每5分钟一次健康检查，维护 health_scores 字典
# router.route() 综合 health_score 排序候选 Provider

class ProviderHealthMonitor:
    def start(self): ...  # 启动后台线程
    def get_score(self, provider_id: str) -> float  # 0.0~1.0
    def record_failure(self, provider_id: str): ...
    def record_success(self, provider_id: str): ...
```

**测试用例**：
```python
def test_health_score_starts_at_1():
    monitor = ProviderHealthMonitor()
    assert monitor.get_score("groq") == 1.0

def test_consecutive_failures_reduce_score():
    monitor = ProviderHealthMonitor()
    for _ in range(5):
        monitor.record_failure("groq")
    assert monitor.get_score("groq") < 0.5

def test_success_recovers_score():
    monitor = ProviderHealthMonitor()
    for _ in range(5):
        monitor.record_failure("groq")
    for _ in range(10):
        monitor.record_success("groq")
    assert monitor.get_score("groq") > 0.8
```

---

### PHASE 3：集成到现有 API

---

#### Task 3.0：Commerce 中间件
**文件**：`backend/commerce/__init__.py`, `backend/commerce/middleware.py`  
**优先级**：P3 | **前置**：Task 1.1, 1.2, 1.3, 2.1, 2.2

**实现内容**：
```python
# 封装完整调用链，供各路由使用
class CommerceContext:
    """一次 AI 调用的完整上下文，管理 Reserve→Execute→Settle→Log 生命周期"""
    
    def __init__(self, db, user_id, capability, quality_tier, plan_id, 
                 request_id, extra=None):
        ...

    def check_permission(self, permission: str) -> bool: ...
    def reserve(self, input_metadata: dict) -> str: ...  # reservation_id
    def get_handle(self, preferred_provider=None) -> ProviderHandle: ...
    def settle(self, actual_usage: dict, provider_id: str, model_id: str,
               latency_ms: int, status: str = "success") -> None: ...
    def release_on_error(self, error: Exception) -> None: ...
```

**典型使用模式**：
```python
# 在 app.py 各路由中使用
ctx = CommerceContext(db, user_id="anonymous", capability="transcription",
                      quality_tier="standard", plan_id="free",
                      request_id=request_id, extra={"video": video_name})

if not ctx.check_permission("CanTranscribe"):
    return jsonify({"error": "权限不足，请升级套餐"}), 403

reservation_id = ctx.reserve({"duration_seconds": duration})
handle = ctx.get_handle(preferred_provider=provider)

try:
    result = call_provider(handle, ...)
    ctx.settle({"duration_seconds": duration}, handle.provider_id, handle.model_id,
               latency_ms=elapsed_ms)
except Exception as e:
    ctx.release_on_error(e)
    raise
```

**测试用例**：
```python
def test_commerce_context_full_flow():
    """验证完整计费链路：reserve→settle→log"""
    db = seeded_db_with_user("u1", plan="plus", credits=500)
    ctx = CommerceContext(db, "u1", "transcription", "standard", "plus", "req-001")
    
    initial_balance = get_balance(db, "u1")["total"]
    reservation_id = ctx.reserve({"duration_seconds": 60})
    assert get_balance(db, "u1")["total"] < initial_balance  # 已预扣
    
    ctx.settle({"duration_seconds": 60}, "groq", "whisper-large-v3", 5000)
    final_balance = get_balance(db, "u1")["total"]
    assert final_balance < initial_balance  # 已扣费
    
    # 验证 usage_log 有记录
    log = get_log(db, ctx.log_id)
    assert log["status"] == "success"
    assert log["credits_charged"] > 0

def test_commerce_context_error_releases():
    """AI 失败时自动释放预扣"""
    db = seeded_db_with_user("u1", plan="plus", credits=500)
    initial_balance = get_balance(db, "u1")["total"]
    
    ctx = CommerceContext(db, "u1", "transcription", "standard", "plus", "req-002")
    ctx.reserve({"duration_seconds": 60})
    ctx.release_on_error(Exception("API timeout"))
    
    assert get_balance(db, "u1")["total"] == initial_balance  # 完全恢复
```

---

#### Task 3.1：集成 /api/transcribe
**文件**：`backend/app.py`（修改）  
**优先级**：P3 | **前置**：Task 3.0

**修改策略**：
- 不改变 HTTP API 路径、参数、响应格式
- 在 `do_transcribe()` 函数入口和出口插入 Commerce 逻辑
- `provider` 参数继续作为 `preferred_provider` 传给 Router
- `duration` 从现有 `get_video_duration()` 获取（已有）
- `latency_ms` 通过 `time.time()` 计算

**关键改动点**：
```python
# 在 do_transcribe() 开始：
duration = get_video_duration(video_path)
ctx = CommerceContext(db, user_id="anonymous", capability="transcription",
                      quality_tier=_quality_for_provider(provider),
                      plan_id="free", request_id=...,
                      extra={"video": video_name})
if not ctx.check_permission("CanTranscribe"):
    progress_queue.put(("error", "权限不足"))
    return
rid = ctx.reserve({"duration_seconds": duration})

# 在 transcribe_video() 成功后：
ctx.settle({"duration_seconds": duration}, provider, model_id, latency_ms=elapsed)

# 在 except 中：
ctx.release_on_error(e)
```

**测试用例**（curl/集成测试）：
```bash
# 测试1：基本连通（有 usage_log 记录）
curl -X POST /api/transcribe -d '{"video":"test.mp4","provider":"groq"}'
# 预期：响应正常 + usage_logs 表有一条新记录

# 测试2：权限拦截（mock 用户为 free，provider=youdao 超出权限）
# 预期：返回 {"error": "权限不足"}, 403

# 测试3：失败时 wallet 恢复（mock provider 抛异常）
# 预期：wallet balance 不变，usage_log status=failed
```

---

#### Task 3.2：集成 /api/translate
**文件**：`backend/app.py`（修改）  
**优先级**：P3 | **前置**：Task 3.0

**注意点**：
- `char_count` = 所有 segments 文本总字符数
- 现有 DeepSeek→Gemini Fallback 需要通知 Router 更新 Health Score
- 返回值中的 `provider` 字段可补充到 usage_log

**测试用例**：
```bash
# 正常翻译
curl -X POST /api/translate -d '{"segments":[...],"source_lang":"泰语","target_lang":"中文"}'
# 预期：翻译成功 + usage_log 记录 capability=translation

# Fallback 触发时的 usage_log
# 预期：fallback_used=true, fallback_from="deepseek", provider_id="gemini"
```

---

#### Task 3.3：集成 /api/tts-generate
**文件**：`backend/app.py`（修改）  
**优先级**：P3 | **前置**：Task 3.0

**注意点**：
- TTS 有两个阶段：content_gen（已记录 tts_content_gen 事件）和 synthesis
- 两阶段分别用 `CommerceContext` 记录两条 usage_log
- `char_count` 来自 `len(text)`（已有）

---

#### Task 3.4：集成 /api/pronounce
**文件**：`backend/app.py`（修改）  
**优先级**：P3 | **前置**：Task 3.0

**注意点**：
- 发音评分无 Fallback，失败直接报错
- `duration_seconds` 从音频文件获取（ffprobe，参考 get_video_duration）

---

#### Task 3.5：集成其他端点
**文件**：`backend/app.py`（修改）  
**优先级**：P3 | **前置**：Task 3.0

覆盖：
- `/api/retranscribe` → capability="transcription"（单句）
- `/api/word-define` → capability="word_definition"
- `/api/romanize` / `/api/romanize-batch` → capability="romanize"（zh=free, th=credits）
- `/api/ocr` → capability="ocr"
- `/api/tts-content` → capability="content_gen"
- `/api/export-srt` / `/api/export` → capability="export"（固定0 credits）

---

### PHASE 4：运营工具

---

#### Task 4.1：扩展 Admin API
**文件**：`backend/app.py`（新增路由）  
**优先级**：P4 | **前置**：Task 1.1~1.3, 2.1

```
GET  /api/admin/commerce/users              # 用户列表 + 余额
GET  /api/admin/commerce/usage?days=7       # 用量报表（按 capability/provider 汇总）
GET  /api/admin/commerce/costs?days=7       # 成本报表（按 provider 汇总 cost_usd）
POST /api/admin/commerce/credits/grant      # 赠送 Credits
     Body: {user_id, amount, type, expires_days, reason}
POST /api/admin/commerce/credits/refund     # 手动退款
     Body: {usage_log_id, amount, reason}
GET  /api/admin/commerce/log/:log_id        # 单条 usage_log 详情
```

**测试用例**：
```bash
# 无 ADMIN_KEY 拒绝
curl /api/admin/commerce/usage → 403

# 有 ADMIN_KEY 返回数据
curl "/api/admin/commerce/usage?key=xxx&days=7" → {by_capability:{...}, by_provider:{...}}

# 赠送credits后余额增加
curl -X POST /api/admin/commerce/credits/grant -d '{"user_id":"u1","amount":100,"type":"gift"}'
```

---

#### Task 4.2：用户余额 API
**文件**：`backend/app.py`（新增路由）  
**优先级**：P4 | **前置**：Task 1.1

```
GET /api/user/wallet          # 当前余额 + 套餐信息
GET /api/user/usage?limit=20  # 最近用量记录
```

**响应格式**：
```json
{
  "balance": {
    "subscription": 847,
    "gift": 50,
    "paid": 200,
    "total": 1097
  },
  "plan": "plus",
  "subscription_expires_at": "2026-08-01T00:00:00Z"
}
```

---

### PHASE 5：生产加固

---

#### Task 5.1：对账机制
**文件**：`backend/commerce/reconcile.py`  
**优先级**：P5

每日运行：usage_logs 中 credits_charged 之和应等于 wallet_transactions 中扣款总和。
误差 > 0.1% 时告警（写日志 + 可配置 webhook）。

#### Task 5.2：Free 套餐 Rate Limiter
**文件**：`backend/commerce/rate_limit.py`  
**优先级**：P5

Free 用户每日最多：
- transcription: 3次
- tts_synthesis: 2次
- pronunciation: 5次

基于内存计数（重启清零，可接受）。

#### Task 5.3：月末 Credits 重置
**文件**：`backend/commerce/cron.py`  
**优先级**：P5

月初 UTC 00:00 自动：
1. 过期 subscription_credits 清零
2. 发放本月新配额（按当前 plan_id）
3. 过期 gift_credits 清零

---

## 四、实施里程碑

```
Week 1     Task 0.1 + 0.2 + 0.3   数据基础，独立测试通过
Week 2     Task 1.1 + 1.2 + 1.3   计费三件套，全部单元测试通过
Week 3     Task 2.1 + 2.2          Permission + Router，集成测试通过
Week 4     Task 3.0 + 3.1 + 3.2   中间件 + 转录/翻译接入，线上验收
Week 5     Task 3.3 + 3.4 + 3.5   其余 API 全部接入
Week 6     Task 4.1 + 4.2          Admin 工具上线，运营可用
Week 7+    Task 5.x                 生产加固
后续        支付集成（Stripe/微信支付）
```

---

## 五、文件结构规划

```
backend/
├── commerce/                   # 新建包（本项目的 AI Commerce Platform）
│   ├── __init__.py             # 导出: get_db, CommerceContext
│   ├── db.py                   # 数据库初始化（init_db, get_db）
│   ├── schema.sql              # DDL（由 db.py 读取执行）
│   ├── seed.py                 # 初始化数据（plan/provider_costs/pricing_policies）
│   ├── identity.py             # Task 0.2
│   ├── wallet.py               # Task 1.1
│   ├── pricing.py              # Task 1.2
│   ├── usage_log.py            # Task 1.3
│   ├── permission.py           # Task 2.1
│   ├── router.py               # Task 2.2
│   ├── health.py               # Task 2.3（可选）
│   ├── middleware.py           # Task 3.0（CommerceContext）
│   ├── reconcile.py            # Task 5.1
│   └── rate_limit.py           # Task 5.2
├── tests/
│   ├── test_wallet.py
│   ├── test_pricing.py
│   ├── test_permission.py
│   ├── test_router.py
│   ├── test_usage_log.py
│   └── test_commerce_integration.py
└── app.py                      # 修改（Phase 3）
```

---

## 六、不变约束（硬性规定）

1. **HTTP API 路径和参数不变**：`/api/transcribe`, `/api/translate` 等路径、参数名、响应格式保持完全兼容
2. **不引入 ORM**：原生 sqlite3/SQL，符合 CLAUDE.md 设计克制原则
3. **不引入消息队列/任务调度框架**：月末 Cron 用简单后台线程或外部触发
4. **不修改 ai/ 和 domain/ 层**：Commerce 层作为 app.py 和 ai/ 层之间的新中间层
5. **不实现支付**：本阶段 wallet.add_credits 只由管理员手动触发
6. **数据库文件不提交 git**：`backend/commerce.db` 加入 .gitignore
