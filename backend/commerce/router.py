"""
AI Router：静态路由表版本。

根据 capability + quality_tier + plan_id 选择 Provider，
兼容现有 API 中的 preferred_provider 参数（用户显式选择）。

调用链位置：
  Permission.check → Router.route → Wallet.Reserve → Provider → UsageLog → Wallet.Confirm

公开函数：
  route(capability, quality_tier, plan_id, preferred_provider, input_metadata) → ProviderHandle
  with_fallback(handle, error) → ProviderHandle | None

ProviderHandle 不持有定价信息（Credits 由 Pricing Engine 按 capability 计算）。

Combined 模式（Groq 断句 + Azure 文字校准）：
  is_composite=True，sub_handles=[groq_handle, azure_handle]
  各 sub_handle 分别触发一条 UsageLog，Credits 合并扣除。

Provider ID 约定（与 provider_costs 表 provider_id 字段一致）：
  groq / openai / azure / gemini / deepseek / youdao / cloudflare / local
"""
from __future__ import annotations
from dataclasses import dataclass, field
from config import get_logger, settings

logger = get_logger(__name__)

# ── 路由表（静态配置） ────────────────────────────────────────────────────────
# 结构：capability → quality_tier → [primary, fallback1, ...]
# 列表顺序 = 优先级顺序；第一个是默认选择，后续是 Fallback Chain

ROUTING_TABLE: dict = {
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
    "tts_synthesis": {
        "economy":  ["azure", "gemini"],
        "standard": ["gemini", "azure"],
        "premium":  ["gemini", "azure"],
    },
    "content_gen": {
        "economy":  ["deepseek", "gemini"],
        "standard": ["gemini", "deepseek"],
        "premium":  ["gemini", "deepseek"],
    },
    "pronunciation": {
        "economy":  ["azure"],          # 唯一选择，无 Fallback
        "standard": ["azure"],
        "premium":  ["azure"],
    },
    "romanize": {
        "economy":  ["local", "gemini"],  # local = pypinyin（中文，免费）
        "standard": ["local", "gemini"],  # zh → local；th → gemini（由调用方决定）
        "premium":  ["gemini", "local"],
    },
    "word_definition": {
        "economy":  ["deepseek", "gemini"],
        "standard": ["deepseek", "gemini"],
        "premium":  ["deepseek", "gemini"],
    },
    "ocr": {
        "economy":  ["gemini"],
        "standard": ["gemini"],
        "premium":  ["gemini"],
    },
    "export": {
        "economy":  ["local"],
        "standard": ["local"],
        "premium":  ["local"],
    },
    "image_gen": {
        "economy":  ["cloudflare", "gemini"],
        "standard": ["cloudflare", "gemini"],
        "premium":  ["gemini", "cloudflare"],
    },
}

# Provider → 默认 model_id 映射（与 provider_costs.model_id 一致）
_PROVIDER_MODELS: dict = {
    "groq":        "whisper-large-v3",
    "openai":      "whisper-1",
    "azure":       "azure-speech",          # transcription / pronunciation
    "azure-tts":   "azure-tts-neural",      # tts_synthesis（特殊别名）
    "gemini":      "gemini-3.1-flash-lite",
    "gemini-tts":  "gemini-3.1-flash-tts",  # tts_synthesis（特殊别名）
    "deepseek":    "deepseek-chat",
    "youdao":      "youdao-tts",
    "cloudflare":  "flux-1-schnell",
    "local":       "pypinyin",              # romanize zh / export
}

# TTS 合成 Provider 的特殊 model 映射
_TTS_PROVIDER_MODELS: dict = {
    "gemini":  "gemini-3.1-flash-tts",
    "azure":   "azure-tts-neural",
    "youdao":  "youdao-tts",
}

# Provider → 默认 timeout（秒）
_PROVIDER_TIMEOUTS: dict = {
    "groq":       settings.TIMEOUT_GROQ,
    "openai":     settings.TIMEOUT_OPENAI,
    "azure":      settings.TIMEOUT_AZURE_RECOGNITION,
    "gemini":     settings.TIMEOUT_GEMINI_DEFAULT,
    "deepseek":   settings.TIMEOUT_DEEPSEEK,
    "youdao":     settings.TIMEOUT_YOUDAO_DEFAULT,
    "cloudflare": settings.TIMEOUT_CF_IMAGE,
    "local":      5,
}

# "combined" 模式：Groq 断句 + Azure 校准，返回 CompositeHandle
_COMBINED_PROVIDERS = ["groq", "azure"]


# ── 数据类 ────────────────────────────────────────────────────────────────────

@dataclass
class ProviderHandle:
    """
    一次 Provider 路由结果。

    不持有 Credits 定价信息（由 Pricing Engine 按 capability 计算）。
    is_composite=True 时 sub_handles 不为空，调用方需逐一执行各 sub_handle。
    """
    provider_id:  str
    model_id:     str
    capability:   str
    timeout:      float
    is_composite: bool = False
    sub_handles:  list = field(default_factory=list)
    # 路由链状态（供 with_fallback 使用，不暴露给业务层）
    _candidates:  list = field(default_factory=list, repr=False)
    _current_idx: int  = field(default=0, repr=False)


# ── 路由 ──────────────────────────────────────────────────────────────────────

def route(
    capability: str,
    quality_tier: str = "standard",
    plan_id: str = "free",
    preferred_provider: str = None,
    input_metadata: dict = None,
) -> ProviderHandle:
    """
    选择 Provider，返回 ProviderHandle。

    优先级：
      1. preferred_provider（用户/前端显式指定，兼容现有 API 参数）
      2. quality_tier + plan_id 路由规则
      3. 内置默认（路由表第一个）
    """
    # "combined" 模式特殊处理
    if preferred_provider == "combined":
        return _make_composite_handle(capability)

    # 获取候选列表
    tier_table = ROUTING_TABLE.get(capability, {})
    candidates = (
        tier_table.get(quality_tier)
        or tier_table.get("standard")
        or ["gemini"]   # 兜底
    )

    # preferred_provider 合法时插队到第一位
    if preferred_provider and preferred_provider in (
        list(_PROVIDER_MODELS.keys()) + ["combined"]
    ):
        if preferred_provider in candidates:
            # 将指定 Provider 移到首位，保留其余 Fallback 顺序
            ordered = [preferred_provider] + [c for c in candidates if c != preferred_provider]
        else:
            # 用户指定了不在路由表里的 Provider（如 openai），直接放首位
            ordered = [preferred_provider] + candidates
        candidates = ordered

    primary = candidates[0]
    handle = _make_handle(primary, capability, candidates, idx=0)
    logger.debug(
        f"[router] {capability}/{quality_tier}/{plan_id} → {primary} "
        f"(fallbacks: {candidates[1:]})"
    )
    return handle


def with_fallback(handle: ProviderHandle, error: Exception) -> "ProviderHandle | None":
    """
    当前 Provider 失败后，返回下一个候选 ProviderHandle。
    无更多候选时返回 None（调用方应向用户报错）。
    """
    if handle.is_composite:
        logger.warning(f"[router] composite handle has no fallback")
        return None

    next_idx = handle._current_idx + 1
    if next_idx >= len(handle._candidates):
        logger.warning(
            f"[router] no more fallback for {handle.capability} "
            f"(exhausted: {handle._candidates})"
        )
        return None

    next_provider = handle._candidates[next_idx]
    logger.info(
        f"[router] fallback: {handle.provider_id} → {next_provider} "
        f"(reason: {error})"
    )
    return _make_handle(next_provider, handle.capability, handle._candidates, idx=next_idx)


# ── 内部 ──────────────────────────────────────────────────────────────────────

def _make_handle(
    provider_id: str,
    capability: str,
    candidates: list,
    idx: int,
) -> ProviderHandle:
    model_id = _resolve_model(provider_id, capability)
    timeout  = _PROVIDER_TIMEOUTS.get(provider_id, settings.TIMEOUT_GEMINI_DEFAULT)
    return ProviderHandle(
        provider_id=provider_id,
        model_id=model_id,
        capability=capability,
        timeout=timeout,
        is_composite=False,
        sub_handles=[],
        _candidates=list(candidates),
        _current_idx=idx,
    )


def _make_composite_handle(capability: str) -> ProviderHandle:
    """创建 combined 模式的 CompositeHandle（Groq + Azure）。"""
    sub_handles = [
        _make_handle(p, capability, _COMBINED_PROVIDERS, idx=i)
        for i, p in enumerate(_COMBINED_PROVIDERS)
    ]
    return ProviderHandle(
        provider_id="combined",
        model_id="combined",
        capability=capability,
        timeout=max(h.timeout for h in sub_handles),
        is_composite=True,
        sub_handles=sub_handles,
        _candidates=[],
        _current_idx=0,
    )


def _resolve_model(provider_id: str, capability: str) -> str:
    """根据 provider_id 和 capability 选择正确的 model_id。"""
    if capability == "tts_synthesis":
        return _TTS_PROVIDER_MODELS.get(provider_id, _PROVIDER_MODELS.get(provider_id, provider_id))
    return _PROVIDER_MODELS.get(provider_id, provider_id)
