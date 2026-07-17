"""
Qwen3-ASR provider — 阿里云 DashScope 语音识别

模型：qwen3-asr-flash-filetrans（异步文件转写，支持词级时间戳）
文档：https://help.aliyun.com/zh/model-studio/qwen-speech-recognition

优势：
- 词级时间戳（begin_time / end_time，毫秒精度）
- 52 种语言（含中文 22 种方言、泰语、日语、韩语）
- 单文件最长 12 小时 / 2 GB
- 对中文/亚洲语言精度高于 Whisper

限制：
- 异步 API（提交 → 轮询 → 取结果），延迟约 1–20 秒
- 需要先将本地文件上传到 DashScope（file:// URI）
- 词级时间戳仅 qwen3-asr-flash-filetrans 支持
- 国际节点：dashscope-intl.aliyuncs.com
"""
import os
import time
import requests

from config import providers, settings, get_logger

logger = get_logger(__name__)

_POLL_INTERVAL = 3    # 轮询间隔秒数
_POLL_MAX_WAIT = 300  # 最长等待 5 分钟


def _transcribe_url() -> str:
    """转写任务提交 URL（去掉尾部 /api/v1，拼 /services/audio/asr/transcription）"""
    base = providers.Qwen.BASE_URL.rstrip("/")
    # base 形如 https://ws-xxx.cn-beijing.maas.aliyuncs.com/api/v1
    return base + "/services/audio/asr/transcription"


def _task_url(task_id: str) -> str:
    base = providers.Qwen.BASE_URL.rstrip("/")
    return base + f"/tasks/{task_id}"


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {providers.Qwen.ASR_API_KEY}"}


# ── 文件上传 ─────────────────────────────────────────────────────────────────

def _upload_file(audio_path: str) -> str:
    """
    将本地音频文件上传到 DashScope，返回 dashscope://{file_id} 格式 URL。
    DashScope 异步转写 API 只接受 URL，不接受本地路径。
    """
    url = providers.Qwen.UPLOAD_URL
    headers = _auth_headers()
    with open(audio_path, "rb") as f:
        resp = requests.post(
            url,
            headers=headers,
            files={
                "file":    (os.path.basename(audio_path), f, "audio/wav"),
                "purpose": (None, "file-extract"),
            },
            timeout=120,
        )
    if not resp.ok:
        # 如果 compatible-mode 上传不可用，尝试 file:// 路径（dashscope SDK >= 1.20 支持）
        logger.warning(f"[qwen_asr] upload HTTP {resp.status_code}: {resp.text[:200]}")
        raise RuntimeError(
            f"DashScope 文件上传失败（{resp.status_code}）: {resp.text[:300]}\n"
            "请确认已安装 dashscope >= 1.20，或者使用环境变量 DASHSCOPE_API_KEY 配置 API Key。"
        )
    data = resp.json()
    file_id = data.get("id") or data.get("file_id") or data.get("output", {}).get("file_id")
    if not file_id:
        raise RuntimeError(f"DashScope upload 响应中没有 file_id: {data}")
    logger.info(f"[qwen_asr] 上传成功 → dashscope://{file_id}")
    return f"dashscope://{file_id}"


def _upload_with_sdk_fallback(audio_path: str) -> str:
    """先尝试 HTTP 上传；若失败则回退到 dashscope SDK 的 file:// 方式。"""
    try:
        return _upload_file(audio_path)
    except Exception as e:
        logger.warning(f"[qwen_asr] HTTP upload 失败，尝试 SDK file:// 方式: {e}")
        # dashscope SDK >= 1.20 支持 file:// URI 自动上传
        abs_path = os.path.abspath(audio_path)
        return f"file://{abs_path}"


# ── 转写请求 ─────────────────────────────────────────────────────────────────

def _submit_task(file_url: str) -> str:
    """提交异步转写任务，返回 task_id。"""
    url = _transcribe_url()
    payload = {
        "model": providers.Qwen.ASR_MODEL,
        "input": {
            "file_urls": [file_url],
        },
        "parameters": {
            "enable_words": True,        # 词级时间戳
            "disfluency_removal_enabled": False,  # 保留原始发音
        },
    }
    resp = requests.post(
        url,
        headers={**_auth_headers(), "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    if not resp.ok:
        raise RuntimeError(f"Qwen ASR 提交失败 ({resp.status_code}): {resp.text[:300]}")
    data     = resp.json()
    task_id  = (data.get("output") or {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"Qwen ASR 响应中无 task_id: {data}")
    logger.info(f"[qwen_asr] 任务已提交 task_id={task_id}")
    return task_id


def _poll_task(task_id: str) -> dict:
    """轮询直到任务完成，返回原始任务结果字典。"""
    url      = _task_url(task_id)
    headers  = _auth_headers()
    deadline = time.time() + _POLL_MAX_WAIT

    while time.time() < deadline:
        time.sleep(_POLL_INTERVAL)
        resp = requests.get(url, headers=headers, timeout=30)
        if not resp.ok:
            logger.warning(f"[qwen_asr] 轮询 HTTP {resp.status_code}")
            continue
        data   = resp.json()
        status = (data.get("output") or {}).get("task_status", "")
        logger.info(f"[qwen_asr] task {task_id} status={status}")

        if status == "SUCCEEDED":
            return data
        if status in ("FAILED", "CANCELED"):
            raise RuntimeError(f"Qwen ASR 任务 {status}: {data}")

    raise TimeoutError(f"Qwen ASR 任务 {task_id} 在 {_POLL_MAX_WAIT}s 内未完成")


# ── 结果解析 ─────────────────────────────────────────────────────────────────

def _fetch_transcript_json(transcription_url: str) -> dict:
    """从 DashScope 返回的 URL 取回转写结果 JSON。"""
    resp = requests.get(transcription_url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _parse_task_result(task_data: dict) -> dict:
    """
    将任务结果解析为项目内部格式：
    {
        "segments": [{"index", "text", "start", "end"}, ...],
        "language": "zh" | "en" | ...,
        "words":    [{"word", "start", "end"}, ...],   # 秒，3 位小数
    }
    """
    results = (task_data.get("output") or {}).get("results", [])
    if not results:
        logger.warning("[qwen_asr] 结果为空")
        return {"segments": [], "language": "unknown", "words": []}

    tr_url = results[0].get("transcription_url", "")
    if not tr_url:
        raise RuntimeError("Qwen ASR 结果中无 transcription_url")

    tr = _fetch_transcript_json(tr_url)
    transcripts = tr.get("transcripts", [])
    if not transcripts:
        return {"segments": [], "language": "unknown", "words": []}

    # 取第一个声道
    ch        = transcripts[0]
    sentences = ch.get("sentences", [])
    lang_raw  = ch.get("language") or tr.get("language") or ""

    segments  = []
    all_words = []

    for i, sent in enumerate(sentences):
        text = (sent.get("text") or "").strip()
        if not text:
            continue
        segments.append({
            "index": i,
            "text":  text,
            "start": round(sent["begin_time"] / 1000.0, 2),
            "end":   round(sent["end_time"]   / 1000.0, 2),
        })
        # 词级时间戳
        for w in sent.get("words", []):
            wt = (w.get("text") or "").strip()
            if wt:
                all_words.append({
                    "word":  wt,
                    "start": round(w["begin_time"] / 1000.0, 3),
                    "end":   round(w["end_time"]   / 1000.0, 3),
                })

    return {
        "segments": segments,
        "language": _norm_lang(lang_raw),
        "words":    all_words,
    }


# ── 语言码归一化 ──────────────────────────────────────────────────────────────

_LANG_MAP = {
    "zh": "zh", "zh-cn": "zh", "zh-tw": "zh",
    "chinese": "zh", "mandarin": "zh", "cantonese": "zh",
    "en": "en", "english": "en",
    "ja": "ja", "japanese": "ja",
    "ko": "ko", "korean": "ko",
    "th": "th", "thai": "th",
    "fr": "fr", "french": "fr",
    "de": "de", "german": "de",
    "es": "es", "spanish": "es",
    "pt": "pt", "portuguese": "pt",
    "ru": "ru", "russian": "ru",
    "it": "it", "italian": "it",
    "ar": "ar", "arabic": "ar",
    "vi": "vi", "vietnamese": "vi",
    "id": "id", "indonesian": "id",
    "hi": "hi", "hindi": "hi",
    "ms": "ms", "malay": "ms",
    "tr": "tr", "turkish": "tr",
}


def _norm_lang(lang: str) -> str:
    if not lang:
        return "unknown"
    return _LANG_MAP.get(lang.lower(), lang[:2].lower() if len(lang) >= 2 else lang)


# ── 公开入口 ──────────────────────────────────────────────────────────────────

def transcribe_file(audio_path: str) -> dict:
    """
    对本地 WAV/MP3 文件进行 Qwen3-ASR 转写。

    流程：
      1. 上传文件到 DashScope → 取得 file URL
      2. 提交异步转写任务
      3. 轮询直到完成
      4. 解析结果为内部格式

    Returns:
        {
            "segments": [{"index", "text", "start", "end"}, ...],
            "language": str,
            "words":    [{"word", "start", "end"}, ...],
        }
    """
    if not providers.Qwen.ASR_API_KEY:
        raise RuntimeError(
            "未配置 DASHSCOPE_API_KEY。请在 .env 或 Railway 环境变量中添加，"
            "并在 https://dashscope.aliyun.com 注册免费账号获取 Key。"
        )

    logger.info(f"[qwen_asr] 开始转写: {os.path.basename(audio_path)}")

    file_url = _upload_with_sdk_fallback(audio_path)
    task_id  = _submit_task(file_url)
    task_data = _poll_task(task_id)
    result    = _parse_task_result(task_data)

    logger.info(
        f"[qwen_asr] 完成: {len(result['segments'])} 句, "
        f"{len(result['words'])} 词, lang={result['language']}"
    )
    return result
