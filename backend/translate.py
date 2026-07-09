import os
import json
import requests

# 中文系目标语言 → DeepSeek；来源是中文 → DeepSeek；其他 → Gemini
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
    return [{"index": s["index"], "text": s["text"],
             "translation": trans_map.get(s["index"], "")} for s in segments]


def _translate_deepseek(segments, source_lang, target_lang):
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("未配置 DEEPSEEK_API_KEY")
    prompt = _build_prompt(segments, source_lang, target_lang)
    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        },
        timeout=30,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _parse_translations(content, segments)


def _translate_gemini(segments, source_lang, target_lang):
    from tts import _gemini_request
    prompt = _build_prompt(segments, source_lang, target_lang)
    result = _gemini_request(
        "gemini-2.0-flash",
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3},
        },
        timeout=30,
        tag="Gemini翻译",
    )
    content = result["candidates"][0]["content"]["parts"][0]["text"]
    return _parse_translations(content, segments)


def translate_segments(segments, source_lang, target_lang, engine="auto"):
    """翻译句子列表。
    engine: "auto"（中文用 DeepSeek，其他用 Gemini）/ "deepseek" / "gemini"
    """
    if not segments:
        return []
    if engine == "auto":
        # 目标是中文，或来源是中文 → DeepSeek；其他语言对 → Gemini
        engine = "deepseek" if (target_lang in _CHINESE_TARGETS or source_lang in _CHINESE_SOURCES) else "gemini"
    if engine == "deepseek":
        return _translate_deepseek(segments, source_lang, target_lang)
    elif engine == "gemini":
        return _translate_gemini(segments, source_lang, target_lang)
    else:
        raise ValueError(f"不支持的翻译引擎: {engine}")
