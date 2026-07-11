"""
拼音 / 罗马拼音生成模块

支持语言：
  zh → 拼音（带声调，pypinyin）
  th → 带音调标记的罗马拼音（Gemini 批量生成）

其他语言不处理，romanization 字段留空。
"""
import json
import re


def _romanize_zh(text):
    try:
        from pypinyin import lazy_pinyin, Style
        return " ".join(lazy_pinyin(text, style=Style.TONE))
    except Exception as e:
        print(f"[romanize] zh error: {e}")
        return ""


def _romanize_th_batch(texts):
    """用 Gemini 为泰语文本批量生成带音调标记的罗马拼音。

    音调标记规则（标在主元音上）：
      中调  无标记   ma
      低调  grave   mà
      降调  circumflex  mâ
      高调  acute   má
      升调  caron   mǎ
    """
    try:
        from tts import _gemini_request
    except ImportError as e:
        print(f"[romanize] Gemini import error: {e}")
        return [""] * len(texts)

    # 过滤空文本，记录原始索引
    indexed = [(i, t) for i, t in enumerate(texts) if t.strip()]
    if not indexed:
        return [""] * len(texts)

    input_json = json.dumps([t for _, t in indexed], ensure_ascii=False)
    prompt = (
        "You are a Thai phonetics expert. Romanize each Thai string with tone marks on the main vowel:\n"
        "  mid=no mark, low=grave(à), falling=circumflex(â), high=acute(á), rising=caron(ǎ)\n"
        "Use hyphens between syllables; keep words separated by spaces.\n"
        "Return ONLY a JSON array of strings in the same order as the input. No explanation.\n\n"
        f"Input: {input_json}"
    )

    try:
        result = _gemini_request(
            "gemini-2.0-flash",
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1},
            },
            timeout=45,
            tag="Romanize-TH",
        )
        content = result["candidates"][0]["content"]["parts"][0]["text"].strip()
        m = re.search(r"\[.*\]", content, re.DOTALL)
        if not m:
            print(f"[romanize] th: no JSON array in response")
            return [""] * len(texts)
        romanized = json.loads(m.group())
    except Exception as e:
        print(f"[romanize] th Gemini error: {e}")
        return [""] * len(texts)

    # 映射回原始位置
    out = [""] * len(texts)
    for (orig_i, _), rom in zip(indexed, romanized):
        out[orig_i] = rom if isinstance(rom, str) else ""
    return out


def generate_romanization(segments, language):
    """
    为 segments 列表中每个 dict 添加 'romanization' 字段。

    Args:
        segments: list of segment dicts（含 'text' 字段）
        language: Whisper 返回的语言代码，如 "th" / "zh" / "en"

    不支持的语言直接返回，不修改 segments。
    """
    lang = (language or "").lower()[:2]

    if lang == "zh":
        for seg in segments:
            text = (seg.get("text") or "").strip()
            seg["romanization"] = _romanize_zh(text) if text else ""

    elif lang == "th":
        texts = [(seg.get("text") or "").strip() for seg in segments]
        romanized = _romanize_th_batch(texts)
        for seg, rom in zip(segments, romanized):
            seg["romanization"] = rom

    # 其他语言（英/日/韩等）：不添加 romanization 字段
