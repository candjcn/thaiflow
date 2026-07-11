"""
拼音 / 罗马拼音生成模块

支持语言：
  zh → 拼音（带声调，pypinyin）
  th → 带音调标记的罗马拼音（Gemini 优先；失败时降级 pythainlp RTGS）

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


def _romanize_th_pythainlp(texts):
    """fallback: pythainlp RTGS（无音调标记，但本地可靠）"""
    try:
        from pythainlp.transliterate import romanize
        out = []
        for t in texts:
            try:
                out.append(romanize(t, engine="royin") if t.strip() else "")
            except Exception:
                out.append("")
        return out
    except Exception as e:
        print(f"[romanize] pythainlp fallback error: {e}")
        return [""] * len(texts)


def _romanize_th_batch(texts):
    """用 Gemini 为泰语文本批量生成带音调标记的罗马拼音。
    Gemini 失败时降级到 pythainlp RTGS（无音调，但保证有输出）。

    Gemini 音调标记规则（标在主元音上）：
      中调  无标记   ma
      低调  grave   mà
      降调  circumflex  mâ
      高调  acute   má
      升调  caron   mǎ
    """
    # 过滤空文本，记录原始索引
    indexed = [(i, t) for i, t in enumerate(texts) if t.strip()]
    if not indexed:
        return [""] * len(texts)

    # ── 尝试 Gemini ──────────────────────────────────────────────
    try:
        from tts import _gemini_request

        input_json = json.dumps([t for _, t in indexed], ensure_ascii=False)
        prompt = (
            "You are a Thai phonetics expert. Romanize each Thai string with tone marks on the main vowel:\n"
            "  mid=no mark, low=grave(à), falling=circumflex(â), high=acute(á), rising=caron(ǎ)\n"
            "Use hyphens between syllables; keep words separated by spaces.\n"
            "Return ONLY a JSON array of strings in the same order as the input. No explanation.\n\n"
            f"Input: {input_json}"
        )
        result = _gemini_request(
            "gemini-3.5-flash",
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1},
            },
            timeout=30,
            max_retries=2,          # 减少重试次数，失败快速降级
            tag="Romanize-TH",
        )
        content = result["candidates"][0]["content"]["parts"][0]["text"].strip()
        m = re.search(r"\[.*\]", content, re.DOTALL)
        if not m:
            raise ValueError(f"no JSON array in Gemini response: {content[:200]}")
        romanized = json.loads(m.group())
        if not isinstance(romanized, list) or len(romanized) != len(indexed):
            raise ValueError(f"unexpected Gemini array length: got {len(romanized)}, expected {len(indexed)}")

        # 映射回原始位置（Gemini 成功）
        out = [""] * len(texts)
        for (orig_i, _), rom in zip(indexed, romanized):
            out[orig_i] = rom if isinstance(rom, str) else ""
        print(f"[romanize] th Gemini OK: {len(indexed)} segments")
        return out

    except Exception as e:
        print(f"[romanize] th Gemini failed ({e}), falling back to pythainlp RTGS")

    # ── Fallback: pythainlp RTGS ─────────────────────────────────
    all_rtgs = _romanize_th_pythainlp(texts)
    non_empty = sum(1 for x in all_rtgs if x)
    print(f"[romanize] pythainlp RTGS: {non_empty}/{len(texts)} segments romanized")
    return all_rtgs


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
