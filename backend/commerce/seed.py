"""
Seed 初始化数据：plan_definitions / provider_costs / pricing_policies。

- run_seed(db)  → 幂等写入（INSERT OR REPLACE），可重复执行
- 所有数值基于市场公开价格，运营可通过 DB 直接调整

定价原则（见 VISION.md）：
  用户看到的是 Credits（能力定价），不是 Provider 单价。
  Credits = provider_cost_usd × multiplier × USD_TO_CREDITS_RATE
"""
import json
import uuid
from config import get_logger

logger = get_logger(__name__)

# ── 套餐定义 ─────────────────────────────────────────────────────────────────

PLAN_DEFINITIONS = {
    "free": {
        "display_name": "免费版",
        "monthly_credits": 100,
        "features": {
            "capabilities": ["transcription", "translation"],
            "permissions": ["CanTranscribe", "CanTranslate"],
            "quality_tiers": ["economy"],
            "max_file_duration_min": 5,
        },
    },
    "plus": {
        "display_name": "Plus 会员",
        "monthly_credits": 1000,
        "features": {
            "capabilities": [
                "transcription", "translation", "tts_synthesis", "content_gen",
                "romanize", "word_definition", "export", "pronunciation",
            ],
            "permissions": [
                "CanTranscribe", "CanTranslate", "CanTTS", "CanTTSContent",
                "CanRomanize", "CanWordDefine", "CanExport", "CanPronunciationAssess",
                "CanUseStandardQuality",
            ],
            "quality_tiers": ["economy", "standard"],
            "max_file_duration_min": 30,
        },
    },
    "pro": {
        "display_name": "Pro 会员",
        "monthly_credits": 5000,
        "features": {
            "capabilities": ["ALL"],
            "permissions": ["ALL"],
            "quality_tiers": ["economy", "standard", "premium"],
            "max_file_duration_min": 120,
        },
    },
    "enterprise": {
        "display_name": "企业版",
        "monthly_credits": 50000,
        "features": {
            "capabilities": ["ALL"],
            "permissions": ["ALL"],
            "quality_tiers": ["ALL"],
            "max_file_duration_min": -1,   # unlimited
        },
    },
}

# ── Provider 成本（基于市场公开价格，2026-07） ────────────────────────────────
# 字段顺序：(provider_id, model_id, capability, unit, unit_price_usd)

PROVIDER_COSTS = [
    # Groq
    ("groq",       "whisper-large-v3",         "transcription",   "per_minute",     0.0001),
    # OpenAI
    ("openai",     "whisper-1",                 "transcription",   "per_minute",     0.006),
    # Azure
    ("azure",      "azure-speech",              "transcription",   "per_minute",     0.0004),
    ("azure",      "azure-speech",              "pronunciation",   "per_minute",     0.0004),
    ("azure",      "azure-tts-neural",          "tts_synthesis",   "per_1k_chars",   0.016),
    # Gemini（flash-lite 文本；flash-tts 语音）
    ("gemini",     "gemini-3.1-flash-lite",     "translation",     "per_1k_tokens",  0.00015),
    ("gemini",     "gemini-3.1-flash-lite",     "content_gen",     "per_1k_tokens",  0.00015),
    ("gemini",     "gemini-3.1-flash-lite",     "romanize",        "per_1k_tokens",  0.00015),
    ("gemini",     "gemini-3.1-flash-lite",     "ocr",             "per_image",      0.002),
    ("gemini",     "gemini-3.1-flash-tts",      "tts_synthesis",   "per_1k_chars",   0.005),
    # DeepSeek
    ("deepseek",   "deepseek-chat",             "translation",     "per_1k_tokens",  0.00014),
    ("deepseek",   "deepseek-chat",             "word_definition", "per_request",    0.001),
    ("deepseek",   "deepseek-chat",             "content_gen",     "per_1k_tokens",  0.00014),
    # Youdao（声音克隆）
    ("youdao",     "youdao-tts",                "tts_synthesis",   "per_1k_chars",   0.01),
    # Cloudflare Workers AI
    ("cloudflare", "flux-1-schnell",            "image_gen",       "per_image",      0.003),
    # Local（pypinyin，永久免费）
    ("local",      "pypinyin",                  "romanize",        "free",           0.0),
]

# ── 定价策略 ──────────────────────────────────────────────────────────────────
# 字段顺序：
#   (capability, quality_tier, plan_id, formula, multiplier, fixed_amount, min_credits, max_credits)
#
# formula:
#   cost_multiplier  → credits = ceil(provider_cost_usd × multiplier × USD_TO_CREDITS_RATE)
#   fixed            → credits = fixed_amount（与 provider 成本无关）

PRICING_POLICIES = [
    # 转录
    ("transcription", "economy",  "all", "cost_multiplier", 2.0, 0, 1, 500),
    ("transcription", "standard", "all", "cost_multiplier", 2.5, 0, 1, 500),
    ("transcription", "premium",  "all", "cost_multiplier", 3.0, 0, 2, 500),
    # 翻译
    ("translation",   "economy",  "all", "cost_multiplier", 2.0, 0, 1, 200),
    ("translation",   "standard", "all", "cost_multiplier", 2.5, 0, 1, 200),
    # TTS 合成
    ("tts_synthesis", "economy",  "all", "cost_multiplier", 2.0, 0, 1, 300),
    ("tts_synthesis", "standard", "all", "cost_multiplier", 2.5, 0, 1, 300),
    ("tts_synthesis", "premium",  "all", "cost_multiplier", 3.0, 0, 2, 300),
    # AI 内容生成
    ("content_gen",   "standard", "all", "cost_multiplier", 2.0, 0, 1, 100),
    # 发音评分
    ("pronunciation", "standard", "all", "cost_multiplier", 2.0, 0, 1, 50),
    # 罗马拼音（中文=本地免费，泰语=固定1 credit）
    ("romanize",      "standard", "all", "fixed",           1.0, 0, 0, 10),  # zh: 0 credits（local provider）
    # 查词
    ("word_definition","standard","all", "fixed",           1.0, 1, 1, 1),
    # OCR
    ("ocr",           "standard", "all", "fixed",           1.0, 2, 2, 2),
    # 导出（本地 ffmpeg，免费）
    ("export",        "standard", "all", "fixed",           1.0, 0, 0, 0),
    # 图像生成
    ("image_gen",     "standard", "all", "fixed",           1.0, 5, 5, 5),
]


# ── 主函数 ────────────────────────────────────────────────────────────────────

def run_seed(db) -> None:
    """
    幂等写入所有初始数据。
    可安全重复执行（INSERT OR REPLACE）。
    """
    _seed_plans(db)
    _seed_provider_costs(db)
    _seed_pricing_policies(db)
    db.commit()
    logger.info("[seed] all seed data written")


def _seed_plans(db) -> None:
    for plan_id, cfg in PLAN_DEFINITIONS.items():
        db.execute(
            """
            INSERT OR REPLACE INTO plan_definitions
                (plan_id, display_name, monthly_credits, features_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                plan_id,
                cfg["display_name"],
                cfg["monthly_credits"],
                json.dumps(cfg["features"], ensure_ascii=False),
            ),
        )
    logger.debug(f"[seed] {len(PLAN_DEFINITIONS)} plans")


def _seed_provider_costs(db) -> None:
    for row in PROVIDER_COSTS:
        provider_id, model_id, capability, unit, unit_price = row
        cost_id = f"{provider_id}:{model_id}:{capability}"
        db.execute(
            """
            INSERT OR REPLACE INTO provider_costs
                (cost_id, provider_id, model_id, capability, unit, unit_price)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (cost_id, provider_id, model_id, capability, unit, unit_price),
        )
    logger.debug(f"[seed] {len(PROVIDER_COSTS)} provider costs")


def _seed_pricing_policies(db) -> None:
    for row in PRICING_POLICIES:
        capability, quality_tier, plan_id, formula, multiplier, fixed_amount, min_credits, max_credits = row
        policy_id = f"{capability}:{quality_tier}:{plan_id}"
        db.execute(
            """
            INSERT OR REPLACE INTO pricing_policies
                (policy_id, capability, quality_tier, plan_id,
                 formula, multiplier, fixed_amount, min_credits, max_credits)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                policy_id, capability, quality_tier, plan_id,
                formula, multiplier, fixed_amount, min_credits, max_credits,
            ),
        )
    logger.debug(f"[seed] {len(PRICING_POLICIES)} pricing policies")
