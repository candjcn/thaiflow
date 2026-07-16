"""
Pricing Engine：Capability → Credits 估算与计算。

核心原则（VISION.md）：
  用户看到的是 Credits（能力定价），不是 Provider 单价。
  同一 capability/quality_tier/plan 的 Credits 对所有 Provider 相同。

公开函数：
  estimate_credits(db, capability, quality_tier, plan_id, input_metadata) → int
    调用 Provider 前估算，含 ESTIMATE_BUFFER_RATIO 余量（默认 10%）。
    返回值直接用于 Wallet.Reserve。

  calculate_credits(db, capability, quality_tier, plan_id,
                    provider_id, model_id, actual_usage) → (int, float)
    Provider 返回后精确计算，返回 (credits, cost_usd)。
    结果写入 UsageLog；不影响用户余额（Confirm 用 estimate）。

input_metadata / actual_usage 键名约定：
  transcription / pronunciation → {"duration_seconds": float}
  translation / content_gen     → {"char_count": int} 或 {"token_count": int}
  tts_synthesis                 → {"char_count": int}
  romanize (th)                 → {"char_count": int}
  romanize (zh, local)          → {}  (free, always 0)
  word_definition / ocr         → {}  (fixed pricing)
  export                        → {}  (free, always 0)
  image_gen                     → {}  (fixed pricing)
"""
import math
from config import get_logger

logger = get_logger(__name__)

# $1 USD = 1000 Credits（运营可调整）
USD_TO_CREDITS_RATE: int = 1000

# estimate 比精确值多出的安全余量（10%）
ESTIMATE_BUFFER_RATIO: float = 0.10

# 每分钟 token 估算（用于 duration_seconds → token_count 的粗估）
_TOKENS_PER_MINUTE: int = 150


def estimate_credits(
    db,
    capability: str,
    quality_tier: str,
    plan_id: str,
    input_metadata: dict,
) -> int:
    """
    调用 Provider 前估算所需 Credits（含 10% 余量）。
    用于 Wallet.Reserve。
    """
    policy = _get_policy(db, capability, quality_tier, plan_id)
    credits = _apply_policy(policy, capability, input_metadata)
    # 对 cost_multiplier 策略追加余量；fixed 策略不加余量（否则会超扣）
    if policy["formula"] == "cost_multiplier" and credits > 0:
        credits = math.ceil(credits * (1 + ESTIMATE_BUFFER_RATIO))
    return credits


def calculate_credits(
    db,
    capability: str,
    quality_tier: str,
    plan_id: str,
    provider_id: str,
    model_id: str,
    actual_usage: dict,
) -> tuple:
    """
    Provider 返回后精确计算 Credits 和成本。

    provider_id / model_id 只用于查询 provider_costs 成本表，
    不影响 Credits 定价（体现 Provider 对用户透明的原则）。

    Returns:
        (credits: int, cost_usd: float)
    """
    policy   = _get_policy(db, capability, quality_tier, plan_id)
    credits  = _apply_policy(policy, capability, actual_usage)
    cost_usd = _calculate_cost_usd(db, provider_id, model_id, capability, actual_usage)
    return credits, cost_usd


# ── 内部：定价策略查询 ────────────────────────────────────────────────────────

def _get_policy(db, capability: str, quality_tier: str, plan_id: str) -> dict:
    """
    按优先级查询定价策略：
      1. capability + quality_tier + plan_id（精确匹配）
      2. capability + quality_tier + 'all'（通用）
      3. capability + 'standard'   + 'all'（降级）
    """
    row = (
        db.execute(
            """
            SELECT formula, multiplier, fixed_amount, min_credits, max_credits
            FROM pricing_policies
            WHERE capability = ? AND quality_tier = ? AND plan_id = ?
            """,
            (capability, quality_tier, plan_id),
        ).fetchone()
        or db.execute(
            """
            SELECT formula, multiplier, fixed_amount, min_credits, max_credits
            FROM pricing_policies
            WHERE capability = ? AND quality_tier = ? AND plan_id = 'all'
            """,
            (capability, quality_tier),
        ).fetchone()
        or db.execute(
            """
            SELECT formula, multiplier, fixed_amount, min_credits, max_credits
            FROM pricing_policies
            WHERE capability = ? AND quality_tier = 'standard' AND plan_id = 'all'
            """,
            (capability,),
        ).fetchone()
    )
    if not row:
        logger.warning(
            f"[pricing] no policy for {capability}/{quality_tier}/{plan_id}, defaulting 1 credit"
        )
        return {
            "formula": "fixed", "multiplier": 1.0,
            "fixed_amount": 1, "min_credits": 1, "max_credits": 9999,
        }
    return dict(row)


def _apply_policy(policy: dict, capability: str, usage: dict) -> int:
    """根据策略类型计算 Credits（不含 estimate buffer）。"""
    formula = policy["formula"]

    if formula == "fixed":
        raw = policy["fixed_amount"]

    elif formula == "cost_multiplier":
        units = _extract_units(capability, usage)
        # 先把 units 换算成 USD，再乘倍率转 Credits
        # 此处用"典型 Provider"成本作为基准；精确成本由 calculate_credits 的 cost_usd 字段记录
        base_cost_usd = _units_to_base_cost(capability, units)
        raw = base_cost_usd * policy["multiplier"] * USD_TO_CREDITS_RATE

    else:
        logger.warning(f"[pricing] unknown formula '{formula}', treating as fixed=1")
        raw = 1

    credits = max(policy["min_credits"], min(policy["max_credits"], math.ceil(raw)))
    return credits


def _extract_units(capability: str, usage: dict) -> float:
    """从 usage dict 提取计费单位数值。"""
    if capability in ("transcription", "pronunciation"):
        return usage.get("duration_seconds", 0) / 60.0   # 转分钟

    if capability in ("translation", "content_gen", "tts_synthesis", "romanize"):
        if "token_count" in usage:
            return usage["token_count"] / 1000.0          # 转 1k tokens
        if "char_count" in usage:
            return usage["char_count"] / 1000.0           # 转 1k chars（per_1k_chars 策略）

    return 0.0


def _units_to_base_cost(capability: str, units: float) -> float:
    """
    用内置典型单价估算基础成本（USD）。
    仅用于 estimate 和 calculate 中的 Credits 换算；
    实际 Provider 单价在 provider_costs 表，由 _calculate_cost_usd 使用。
    """
    # 典型单价（与最便宜 Provider 对齐，保守估算）
    BASE_COST = {
        "transcription":  0.0001,   # groq per_minute
        "translation":    0.00014,  # deepseek per_1k_tokens（视为 per_1k_chars）
        "content_gen":    0.00014,
        "tts_synthesis":  0.005,    # gemini per_1k_chars
        "pronunciation":  0.0004,   # azure per_minute
        "romanize":       0.00015,  # gemini per_1k_tokens
    }
    unit_cost = BASE_COST.get(capability, 0.001)
    return units * unit_cost


# ── 内部：实际成本计算 ────────────────────────────────────────────────────────

def _calculate_cost_usd(
    db,
    provider_id: str,
    model_id: str,
    capability: str,
    actual_usage: dict,
) -> float:
    """查 provider_costs 表，计算本次调用实际成本 USD。"""
    row = db.execute(
        """
        SELECT unit, unit_price
        FROM provider_costs
        WHERE provider_id = ? AND model_id = ? AND capability = ?
        """,
        (provider_id, model_id, capability),
    ).fetchone()

    if not row:
        logger.debug(
            f"[pricing] no cost entry for {provider_id}/{model_id}/{capability}"
        )
        return 0.0

    unit       = row["unit"]
    unit_price = row["unit_price"]

    if unit == "free" or unit_price == 0:
        return 0.0

    qty = _get_quantity(unit, actual_usage)
    return qty * unit_price


def _get_quantity(unit: str, usage: dict) -> float:
    """将 actual_usage 转换为 provider_costs.unit 对应的数量。"""
    if unit == "per_minute":
        return usage.get("duration_seconds", 0) / 60.0

    if unit in ("per_1k_chars", "per_1k_tokens"):
        if "token_count" in usage:
            return usage["token_count"] / 1000.0
        if "char_count" in usage:
            return usage["char_count"] / 1000.0
        return 0.0

    if unit == "per_image":
        return float(usage.get("image_count", 1))

    if unit == "per_request":
        return 1.0

    return 0.0
