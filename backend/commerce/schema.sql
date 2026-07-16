-- ReelSpeak Commerce Platform — SQLite Schema
-- 版本: v1.0  更新: 2026-07-16
-- 注意: tx_type 枚举为 reserve/confirm/release/add/refund（见 ARCHITECTURE.md v1.1）

-- ── 用户表 ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    user_id     TEXT PRIMARY KEY,
    email       TEXT UNIQUE,
    status      TEXT NOT NULL DEFAULT 'active',   -- active/suspended/deleted
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── 套餐定义（运营配置） ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS plan_definitions (
    plan_id         TEXT PRIMARY KEY,              -- free/plus/pro/enterprise
    display_name    TEXT NOT NULL,
    monthly_credits INTEGER NOT NULL DEFAULT 0,
    features_json   TEXT,                          -- JSON: capabilities, permissions, quality_tiers 等
    effective_from  TEXT
);

-- ── 用户订阅 ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_subscriptions (
    sub_id           TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    plan_id          TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'active',  -- active/expired/cancelled
    started_at       TEXT,
    expires_at       TEXT,
    credits_quota    INTEGER NOT NULL DEFAULT 0,
    credits_reset_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

-- ── Wallet（用户账本） ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wallets (
    wallet_id               TEXT PRIMARY KEY,
    user_id                 TEXT NOT NULL UNIQUE,
    subscription_credits    INTEGER NOT NULL DEFAULT 0,
    subscription_expires_at TEXT,
    gift_credits            INTEGER NOT NULL DEFAULT 0,
    paid_credits            INTEGER NOT NULL DEFAULT 0,
    version                 INTEGER NOT NULL DEFAULT 0,  -- 乐观锁
    updated_at              TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

-- ── Wallet 流水 ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wallet_transactions (
    tx_id       TEXT PRIMARY KEY,
    wallet_id   TEXT NOT NULL,
    tx_type     TEXT NOT NULL,   -- reserve/confirm/release/add/refund
    amount      INTEGER NOT NULL, -- 正=入账，负=扣除（从用户视角）
    credit_type TEXT,            -- subscription/gift/paid
    ref_id      TEXT,            -- usage_log_id 或 order_id
    note        TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (wallet_id) REFERENCES wallets (wallet_id)
);

-- ── Provider 成本表（运营维护） ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS provider_costs (
    cost_id     TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,   -- groq/azure/gemini/deepseek/youdao/cloudflare/local
    model_id    TEXT NOT NULL,
    capability  TEXT NOT NULL,   -- transcription/translation/tts/romanize/...
    unit        TEXT NOT NULL,   -- per_minute/per_1k_chars/per_1k_tokens/per_image/per_request/free
    unit_price  REAL NOT NULL,   -- USD
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── 定价策略（运营维护） ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pricing_policies (
    policy_id      TEXT PRIMARY KEY,
    capability     TEXT NOT NULL,
    quality_tier   TEXT NOT NULL DEFAULT 'standard',  -- economy/standard/premium
    plan_id        TEXT NOT NULL DEFAULT 'all',
    formula        TEXT NOT NULL DEFAULT 'cost_multiplier',  -- fixed/cost_multiplier
    multiplier     REAL NOT NULL DEFAULT 3.0,
    fixed_amount   INTEGER NOT NULL DEFAULT 0,
    min_credits    INTEGER NOT NULL DEFAULT 1,
    max_credits    INTEGER NOT NULL DEFAULT 9999,
    effective_from TEXT,
    effective_to   TEXT
);

-- ── Usage Log v2 ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS usage_logs (
    log_id             TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL,
    capability         TEXT NOT NULL,
    quality_tier       TEXT NOT NULL DEFAULT 'standard',
    provider_id        TEXT,
    model_id           TEXT,
    plan_id            TEXT,
    input_units        REAL,
    input_unit_type    TEXT,     -- seconds/chars/tokens/images/requests
    provider_cost_usd  REAL,
    credits_reserved   INTEGER NOT NULL DEFAULT 0,
    credits_charged    INTEGER NOT NULL DEFAULT 0,
    credits_refunded   INTEGER NOT NULL DEFAULT 0,
    latency_ms         INTEGER,
    status             TEXT NOT NULL DEFAULT 'success',  -- success/failed/refunded/timeout
    error_code         TEXT,
    retry_count        INTEGER NOT NULL DEFAULT 0,
    fallback_used      INTEGER NOT NULL DEFAULT 0,       -- 0/1 boolean
    fallback_from      TEXT,
    requested_at       TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at       TEXT,
    reservation_id     TEXT,
    request_id         TEXT,
    extra_json         TEXT     -- 额外元数据 JSON（如 video_name, language）
);

-- ── Permission 手动授权 ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS permission_grants (
    grant_id    TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    permission  TEXT NOT NULL,   -- CanTranscribe/CanTTS/...
    granted_by  TEXT,
    expires_at  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── 索引 ──────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_usage_logs_user     ON usage_logs (user_id, requested_at);
CREATE INDEX IF NOT EXISTS idx_wallet_tx_wallet    ON wallet_transactions (wallet_id, created_at);
CREATE INDEX IF NOT EXISTS idx_permission_user     ON permission_grants (user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_user  ON user_subscriptions (user_id);
