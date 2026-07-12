"""
Cloudflare Workers AI Provider
用于图片生成（FLUX Schnell / SDXL Lightning）。
API 文档：https://developers.cloudflare.com/workers-ai/models/
"""
import requests
from config import providers, get_logger

logger = get_logger(__name__)


def generate_image(prompt, model=None, timeout=30):
    """
    调用 Cloudflare Workers AI 生成图片。

    Args:
        prompt: 英文描述文字
        model:  模型名，默认用 providers.CloudflareAI.IMAGE_MODEL
        timeout: 请求超时秒数

    Returns:
        bytes  — 图片原始字节（JPEG 或 PNG）

    Raises:
        ValueError: 未配置 CF_AI_API_TOKEN
        requests.HTTPError: HTTP 错误
        RuntimeError: 返回结果不含图片
    """
    token = providers.CloudflareAI.API_TOKEN
    if not token:
        raise ValueError("未配置 CF_AI_API_TOKEN（在 Cloudflare Dashboard → API Tokens 创建）")

    account_id = providers.CloudflareAI.ACCOUNT_ID
    if not account_id:
        raise ValueError("未配置 R2_ACCOUNT_ID（与 Workers AI 共用）")

    model = model or providers.CloudflareAI.IMAGE_MODEL
    url = providers.CloudflareAI.BASE_URL.format(
        account_id=account_id, model=model
    )

    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={"prompt": prompt, "num_steps": 4},
        timeout=timeout,
    )
    resp.raise_for_status()

    # Workers AI 图片接口直接返回二进制图片
    content_type = resp.headers.get("content-type", "")
    if content_type.startswith("image/"):
        return resp.content

    # 部分模型返回 JSON 包装
    try:
        data = resp.json()
        # {"result": {"image": "<base64>"}}
        import base64
        b64 = data.get("result", {}).get("image") or data.get("image")
        if b64:
            return base64.b64decode(b64)
    except Exception:
        pass

    raise RuntimeError(f"Workers AI 未返回图片 (content-type: {content_type})")
