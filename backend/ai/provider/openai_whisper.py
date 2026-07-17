"""
OpenAI Transcription Provider
唯一职责：通过 OpenAI SDK 调用转写 API。
文件命名为 openai_whisper.py 以避免与顶层 openai 包名冲突。
"""
from config import providers, settings, get_logger

logger = get_logger(__name__)


def transcribe_file(path, timestamp_granularities=None):
    """识别音频文件，返回 SDK 原始响应对象（含 .segments, .words, .language）。

    Args:
        path: WAV / 音频文件路径
        timestamp_granularities: 如 ["segment", "word"]
    Returns:
        OpenAI SDK 的 Transcription 对象
    Raises:
        ValueError: 未配置 OPENAI_API_KEY
    """
    from openai import OpenAI

    api_key = providers.OpenAI.API_KEY
    if not api_key:
        raise ValueError("未配置 OPENAI_API_KEY")

    client = OpenAI(api_key=api_key, timeout=settings.TIMEOUT_OPENAI)
    kw = {
        "model": providers.OpenAI.WHISPER_MODEL,
        "response_format": "verbose_json",
    }
    if timestamp_granularities:
        kw["timestamp_granularities"] = timestamp_granularities

    with open(path, "rb") as f:
        return client.audio.transcriptions.create(file=f, **kw)


def transcribe_text(path):
    """识别音频文件，返回纯文本字符串。

    适用于 gpt-4o-transcribe 这类不返回 word 级时间戳的模型。
    """
    from openai import OpenAI

    api_key = providers.OpenAI.API_KEY
    if not api_key:
        raise ValueError("未配置 OPENAI_API_KEY")

    client = OpenAI(api_key=api_key, timeout=settings.TIMEOUT_OPENAI)
    kw = {
        "model": providers.OpenAI.TRANSCRIBE_MODEL,
        "response_format": "text",
    }

    with open(path, "rb") as f:
        return client.audio.transcriptions.create(file=f, **kw)
