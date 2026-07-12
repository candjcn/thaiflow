"""
DeepSeek Provider
唯一职责：向 DeepSeek Chat Completion API 发请求，返回模型回复内容字符串。
"""
import requests as _requests
from config import providers, settings, get_logger

logger = get_logger(__name__)


def chat(prompt, temperature=0.3, timeout=None):
    """发送单轮 chat completion 请求，返回模型回复内容字符串。

    Args:
        prompt: 用户消息文本
        temperature: 生成温度（0~1）
        timeout: 请求超时秒数，None 时使用 settings.TIMEOUT_TRANSLATE
    Returns:
        模型回复的文本字符串
    Raises:
        ValueError: 未配置 DEEPSEEK_API_KEY
        requests.HTTPError: HTTP 错误
    """
    api_key = providers.DeepSeek.API_KEY
    if not api_key:
        raise ValueError("未配置 DEEPSEEK_API_KEY")
    if timeout is None:
        timeout = settings.TIMEOUT_TRANSLATE

    resp = _requests.post(
        providers.DeepSeek.BASE_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": providers.DeepSeek.MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
