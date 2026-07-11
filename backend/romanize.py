"""
拼音 / 罗马拼音生成模块

支持语言：
  zh → 拼音（带声调，pypinyin）
  th → RTGS 罗马拼音（pythainlp，已在 requirements.txt）

其他语言不处理，romanization 字段留空。
"""


def _romanize_zh(text):
    try:
        from pypinyin import lazy_pinyin, Style
        return " ".join(lazy_pinyin(text, style=Style.TONE))
    except Exception as e:
        print(f"[romanize] zh error: {e}")
        return ""


def _romanize_th(text):
    try:
        from pythainlp.transliterate import romanize
        return romanize(text, engine="royin") or ""
    except Exception as e:
        print(f"[romanize] th error: {e}")
        return ""


# 哪些 Whisper 语言代码需要生成罗马拼音
_HANDLERS = {
    "zh": _romanize_zh,
    "th": _romanize_th,
}


def generate_romanization(segments, language):
    """
    为 segments 列表中每个 dict 添加 'romanization' 字段。

    Args:
        segments: list of segment dicts（含 'text' 字段）
        language: Whisper 返回的语言代码，如 "th" / "zh" / "en"

    不支持的语言直接返回，不修改 segments。
    """
    lang = (language or "").lower()[:2]
    fn = _HANDLERS.get(lang)
    if fn is None:
        return  # 英语、日语等不处理

    for seg in segments:
        text = (seg.get("text") or "").strip()
        seg["romanization"] = fn(text) if text else ""
