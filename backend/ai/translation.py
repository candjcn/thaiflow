"""
翻译服务层
业务模块通过此模块访问翻译能力，不知道底层是 DeepSeek 还是 Gemini。
保持与原 translate.py 完全相同的函数签名和返回格式。
"""
import json
from config import providers, settings, get_logger
from ai.provider import gemini as gemini_provider
from ai.provider import deepseek as deepseek_provider

logger = get_logger(__name__)

_CHINESE_TARGETS = {"中文", "繁體中文"}
_CHINESE_SOURCES = {"中文", "繁體中文", "普通话"}


def _build_prompt(segments, source_lang, target_lang):
    lines = [f'{seg["index"]}. {seg["text"]}' for seg in segments]
    examples = {
        "中文":    '[{"index":0,"translation":"你好"},{"index":1,"translation":"谢谢"}]',
        "繁體中文": '[{"index":0,"translation":"你好"},{"index":1,"translation":"謝謝"}]',
        "English": '[{"index":0,"translation":"Hello"},{"index":1,"translation":"Thank you"}]',
        "ไทย":    '[{"index":0,"translation":"สวัสดี"},{"index":1,"translation":"ขอบคุณ"}]',
    }
    example = examples.get(target_lang, '[{"index":0,"translation":"..."}]')
    return (
        f"请将以下{source_lang}句子逐句翻译为{target_lang}。\n"
        f"严格按照 JSON 数组格式返回，每个元素包含 index 和 translation 字段。\n"
        f"只返回 JSON，不要任何其他文字。\n\n"
        f"示例返回格式：\n{example}\n\n"
        f"待翻译内容：\n" + "\n".join(lines)
    )


def _parse_translations(content, segments):
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        content = content.rsplit("```", 1)[0]
    translations = json.loads(content)
    trans_map = {t["index"]: t["translation"] for t in translations}
    return [
        {"index": s["index"], "text": s["text"],
         "translation": trans_map.get(s["index"], "")}
        for s in segments
    ]


def translate_segments(segments, source_lang, target_lang, engine="auto"):
    """翻译句子列表。

    Args:
        segments: [{"index": int, "text": str}, ...]
        source_lang: 源语言名称（如 "泰语"）
        target_lang: 目标语言名称（如 "中文"）
        engine: "auto" | "deepseek" | "gemini"
    Returns:
        (results, provider)
        results: [{"index": int, "text": str, "translation": str}, ...]
        provider: "deepseek" | "gemini"
    """
    if not segments:
        return [], "skipped"

    prompt = _build_prompt(segments, source_lang, target_lang)

    if engine == "gemini":
        content = _call_gemini(prompt, source_lang, target_lang)
        provider = "gemini"
    else:
        try:
            content = deepseek_provider.chat(
                prompt, temperature=0.3, timeout=settings.TIMEOUT_TRANSLATE
            )
            logger.info(f"[翻译] DeepSeek OK ({source_lang}→{target_lang})")
            provider = "deepseek"
        except Exception as e:
            logger.warning(f"[翻译] DeepSeek 失败 ({e})，降级到 Gemini")
            content = _call_gemini(prompt, source_lang, target_lang)
            provider = "gemini"

    return _parse_translations(content, segments), provider


def _call_gemini(prompt, source_lang, target_lang):
    result = gemini_provider.request(
        providers.Gemini.TEXT_MODEL,
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3},
        },
        timeout=settings.TIMEOUT_TRANSLATE,
        tag="Gemini翻译",
    )
    content = result["candidates"][0]["content"]["parts"][0]["text"]
    logger.info(f"[翻译] Gemini OK ({source_lang}→{target_lang})")
    return content


def word_define(word, source_lang, target_lang, context=""):
    """查询单词释义（DeepSeek）。

    Returns:
        {"meaning": str, "pos": str}
    Raises:
        json.JSONDecodeError / requests.HTTPError
    """
    ctx_hint = f'\n该词出现在以下句子中："{context}"' if context else ""
    prompt = (
        f"请用{target_lang}简洁解释以下{source_lang}单词的含义。{ctx_hint}\n"
        f"单词：{word}\n\n"
        f"严格按 JSON 返回，格式：{{\"meaning\": \"释义\", \"pos\": \"词性\"}}\n"
        f"释义不超过15个字，词性用缩写（n./v./adj./adv./conj./prep./pron./interj.）。\n"
        f"只返回 JSON，不要其他文字。"
    )
    content = deepseek_provider.chat(
        prompt, temperature=0.2, timeout=settings.TIMEOUT_WORD_DEFINE
    )
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(content.strip())


def choose_transcription(candidates, language):
    """从多个 ASR 候选中选出或修正最可信的原文。"""
    texts = [str(text).strip() for text in candidates if str(text).strip()]
    if not texts:
        return ""
    if len(texts) == 1:
        return texts[0]
    prompt = (
        f"以下是同一段{language or '外语'}音频由不同语音识别引擎产生的候选文本。\n"
        "请结合各候选的共同部分，返回最可能准确的原文；可以修正明显错字，但不要翻译、解释或添加内容。\n"
        "只返回最终原文。\n\n" +
        "\n".join(f"候选{i + 1}: {text}" for i, text in enumerate(texts))
    )
    try:
        return deepseek_provider.chat(
            prompt, temperature=0.1, timeout=settings.TIMEOUT_TRANSLATE
        ).strip()
    except Exception as exc:
        logger.warning(f"[ASR仲裁] DeepSeek 失败 ({exc})，降级到 Gemini")
        return _call_gemini(prompt, language or "外语", language or "外语").strip()
