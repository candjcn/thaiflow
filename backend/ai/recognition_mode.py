"""
识别模式注册表。

目标：
1. 前端只暴露“速度优先 / 平衡 / 准确率优先”。
2. 后端保留可扩展注册表，便于未来接入更多 ASR provider 或策略。
3. 向后兼容老接口中的 provider 参数。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Tuple


@dataclass(frozen=True)
class RecognitionMode:
    key: str
    label: str
    description: str
    preferred_provider: str
    provider_candidates: Tuple[str, ...]
    enable_groq_retry: bool = False
    ui_visible: bool = True

    def to_public_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "preferred_provider": self.preferred_provider,
            "provider_candidates": list(self.provider_candidates),
            "enable_groq_retry": self.enable_groq_retry,
        }


_MODE_REGISTRY: Dict[str, RecognitionMode] = {}

# accuracy mode 的语言优先级表。
# 这里先放“可解释、可维护”的默认顺序，后续应基于泰语/其他语言回归结果持续调整。
_ACCURACY_LANGUAGE_PROVIDER_ORDER = {
    "th": ("groq", "openai", "gemini", "qwen"),
    "en": ("gemini", "openai", "groq", "qwen"),
    "zh": ("qwen", "groq", "openai", "gemini"),
    "ja": ("openai", "qwen", "groq", "gemini"),
    "ko": ("qwen", "groq", "openai", "gemini"),
    "vi": ("groq", "openai", "gemini", "qwen"),
    "fr": ("openai", "gemini", "groq", "qwen"),
    "de": ("openai", "gemini", "groq", "qwen"),
    "es": ("openai", "gemini", "groq", "qwen"),
    "pt": ("openai", "gemini", "groq", "qwen"),
    "ru": ("openai", "gemini", "groq", "qwen"),
    "it": ("openai", "gemini", "groq", "qwen"),
}

_ACCURACY_DEFAULT_ORDER = ("groq", "gemini", "openai", "qwen")

# 单句二次识别是纠错场景，与整段首次识别的速度/断句诉求不同。
# 基于泰语回归集和人工复核，Gemini 固定为首选；其余 provider 仅用于失败或重复结果回退。
_RETRANSCRIPTION_PROVIDER_ORDER = ("gemini", "openai", "groq", "qwen")


def register_mode(mode: RecognitionMode) -> RecognitionMode:
    _MODE_REGISTRY[mode.key] = mode
    return mode


def get_mode(key: str) -> RecognitionMode | None:
    return _MODE_REGISTRY.get((key or "").strip().lower())


def list_visible_modes() -> list[dict]:
    return [m.to_public_dict() for m in _MODE_REGISTRY.values() if m.ui_visible]


def get_accuracy_provider_candidates(language: str | None = None) -> tuple[str, ...]:
    """返回 accuracy mode 在给定语言下的候选 provider 顺序。"""
    lang = (language or "").strip().lower()[:2]
    order = _ACCURACY_LANGUAGE_PROVIDER_ORDER.get(lang, _ACCURACY_DEFAULT_ORDER)
    seen = set()
    result = []
    for provider in order:
        if provider and provider not in seen:
            seen.add(provider)
            result.append(provider)
    return tuple(result)


def get_retranscription_provider_candidates(language: str | None = None) -> tuple[str, ...]:
    """返回单句二次识别候选顺序；保留 language 参数供后续按语言调优。"""
    del language
    return _RETRANSCRIPTION_PROVIDER_ORDER


def _legacy_provider_mode(provider: str) -> RecognitionMode:
    provider = (provider or "").strip().lower()
    labels = {
        "groq": ("Groq Whisper", "兼容旧默认行为：Groq 主识别，保留短视频低置信度补强。"),
        "openai": ("OpenAI Whisper", "兼容旧接口：直接使用 OpenAI 识别。"),
        "azure": ("Azure Speech", "兼容旧接口：直接使用 Azure 识别。"),
        "combined": ("Groq + Azure", "兼容旧接口：Groq 断句 + Azure 校准。"),
        "qwen": ("Qwen3-ASR", "兼容旧接口：直接使用 Qwen3-ASR。"),
    }
    label, desc = labels.get(provider, ("平衡（默认）", "默认的平衡识别策略。"))
    if provider == "groq":
        return RecognitionMode(
            key="balanced",
            label="平衡（默认）",
            description="Groq 主识别，短视频保留低置信度补强。",
            preferred_provider="groq",
            provider_candidates=("groq",),
            enable_groq_retry=True,
        )
    if provider == "qwen":
        return RecognitionMode(
            key="accuracy",
            label="准确率优先",
            description="Qwen3-ASR 优先；仅作兼容回退，不向普通用户暴露。",
            preferred_provider="qwen",
            provider_candidates=("qwen",),
            enable_groq_retry=False,
            ui_visible=False,
        )
    return RecognitionMode(
        key=provider or "balanced",
        label=label,
        description=desc,
        preferred_provider=provider or "groq",
        provider_candidates=(provider or "groq",),
        enable_groq_retry=(provider in ("groq", "openai")),
        ui_visible=False,
    )


# ── 公开模式：仅给前端选择 ──────────────────────────────────────────────────
register_mode(
    RecognitionMode(
        key="speed",
        label="速度优先",
        description="更快完成识别，尽量减少额外重试。",
        preferred_provider="groq",
        provider_candidates=("groq",),
        enable_groq_retry=False,
    )
)
register_mode(
    RecognitionMode(
        key="balanced",
        label="平衡（默认）",
        description="默认方案：兼顾速度和准确率，适合大多数短视频。",
        preferred_provider="groq",
        provider_candidates=("groq",),
        enable_groq_retry=True,
    )
)
register_mode(
    RecognitionMode(
        key="accuracy",
        label="准确率优先",
        description="优先尝试更强的识别引擎，适合泰语等更难的样本。",
        preferred_provider="groq",
        provider_candidates=("groq", "gemini", "openai", "qwen"),
        enable_groq_retry=True,
    )
)


def resolve_recognition_mode(
    recognition_mode: str | None = None,
    provider: str | None = None,
) -> RecognitionMode:
    """
    将前端模式或旧 provider 参数转换为识别策略。

    优先级：
      1. recognition_mode（新接口）
      2. provider（旧接口兼容）
      3. balanced 默认
    """
    key = (recognition_mode or "").strip().lower()
    if key:
        mode = get_mode(key)
        if mode:
            return mode

    if provider:
        return _legacy_provider_mode(provider)

    return get_mode("balanced")  # type: ignore[return-value]


def iter_candidate_providers(mode: RecognitionMode) -> Iterable[str]:
    return mode.provider_candidates or ("groq",)
