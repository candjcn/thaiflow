"""
Groq Whisper Provider
唯一职责：通过 OpenAI 兼容 SDK 调用 Groq Whisper API。
API Key / Base URL / 模型名一律来自 config.providers，不在此硬编码。
"""
from config import providers, settings, get_logger

logger = get_logger(__name__)


def transcribe_file(path, timestamp_granularities=None, language=None):
    """识别音频 / 视频文件，返回 SDK 原始响应对象（含 .segments, .words, .language）。

    Args:
        path: 音频或视频文件路径（Groq 支持直接上传 mp4）
        timestamp_granularities: 如 ["segment", "word"]
    Returns:
        OpenAI SDK 的 Transcription 对象
    Raises:
        ValueError: 未配置 GROQ_API_KEY
    """
    from openai import OpenAI

    api_key = providers.Groq.API_KEY
    if not api_key:
        raise ValueError("未配置 GROQ_API_KEY")

    client = OpenAI(api_key=api_key, base_url=providers.Groq.BASE_URL)
    kw = {
        "model": providers.Groq.WHISPER_MODEL,
        "response_format": "verbose_json",
    }
    if timestamp_granularities:
        kw["timestamp_granularities"] = timestamp_granularities
    if language:
        kw["language"] = language

    with open(path, "rb") as f:
        return client.audio.transcriptions.create(file=f, **kw)


def transcribe_text(wav_path, language=None):
    """识别短音频，只返回纯文本字符串（用于切片重识别和低置信度补录）。

    Args:
        wav_path: WAV 文件路径
        language: 可选语言代码（如 "th"），提高准确率
    Returns:
        识别出的文本字符串，失败时返回空字符串
    """
    from openai import OpenAI

    api_key = providers.Groq.API_KEY
    if not api_key:
        return ""

    client = OpenAI(
        api_key=api_key,
        base_url=providers.Groq.BASE_URL,
        timeout=settings.TIMEOUT_GROQ,
    )
    kw = {"model": providers.Groq.WHISPER_MODEL, "response_format": "text"}
    if language:
        kw["language"] = language

    with open(wav_path, "rb") as f:
        result = client.audio.transcriptions.create(file=f, **kw)
    return result if isinstance(result, str) else ""
