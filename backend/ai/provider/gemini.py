"""
Gemini HTTP Provider
唯一职责：向 Google Generative Language API 发请求，处理限流 / 重试 / 超时。
其他模块通过 ai.provider.gemini.request() 调用，不得自行构造 Gemini HTTP 请求。
"""
import time
import requests as _requests
from config import providers, settings, get_logger

logger = get_logger(__name__)

# URL 模板（v1 用于正式模型；v1beta 用于预览模型如 TTS / 图片生成）
URL_V1     = providers.Gemini.URL_V1
URL_V1BETA = providers.Gemini.URL_V1BETA


def _key():
    key = settings.GEMINI_API_KEY
    if not key:
        raise RuntimeError("请配置 GEMINI_API_KEY")
    return key


def request(model, payload, timeout=60, max_retries=4, tag="Gemini", url_tpl=None):
    """统一的 Gemini HTTP 调用：429 限流和 5xx 高负载自动退避重试。

    Args:
        model: 模型名称（如 "gemini-2.0-flash"）
        payload: 请求体 dict（contents / generationConfig 等）
        timeout: 单次请求超时秒数
        max_retries: 最大重试次数（含首次）
        tag: 日志前缀
        url_tpl: 覆盖默认 URL_V1；预览模型传 URL_V1BETA
    Returns:
        API 响应的 JSON dict
    Raises:
        RuntimeError: 所有重试均失败
    """
    if url_tpl is None:
        url_tpl = URL_V1
    last_err = ""
    attempts_made = 0
    for attempt in range(max_retries):
        attempts_made = attempt + 1
        try:
            resp = _requests.post(
                url_tpl.format(model=model, key=_key()),
                json=payload,
                timeout=timeout,
            )
            if resp.status_code == 200:
                return resp.json()
            last_err = f"{resp.status_code}: {resp.text[:300]}"
            if resp.status_code == 429:
                wait = 15 * (attempt + 1)
                logger.warning(f"[{tag}] 限流，{wait}s 后重试（{attempt + 1}/{max_retries}）")
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                wait = 5 * (attempt + 1)
                logger.warning(
                    f"[{tag}] 服务繁忙 {resp.status_code}，{wait}s 后重试（{attempt + 1}/{max_retries}）"
                )
                time.sleep(wait)
                continue
            break  # 其他 4xx（如 404 模型不存在）不重试
        except _requests.RequestException as e:
            last_err = str(e)[:300]
            time.sleep(3 * (attempt + 1))

    raise RuntimeError(f"{tag} 失败（尝试 {attempts_made} 次）{last_err}")
