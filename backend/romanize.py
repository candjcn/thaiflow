"""
拼音 / 罗马拼音生成模块

支持语言：
  zh → 拼音（带声调，pypinyin）
  th → 带音调标记的罗马拼音（Gemini 优先；失败时降级 pythainlp RTGS）

其他语言不处理，romanization 字段留空。
"""
import json
import re
from config import providers, get_logger

logger = get_logger(__name__)


def _romanize_zh(text):
    try:
        from pypinyin import lazy_pinyin, Style
        return " ".join(lazy_pinyin(text, style=Style.TONE))
    except Exception as e:
        logger.warning(f"[romanize] zh error: {e}")
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
        logger.warning(f"[romanize] pythainlp fallback error: {e}")
        return [""] * len(texts)


def _romanize_th_batch(texts):
    """为泰语文本批量生成带音调标记的罗马拼音。
    优先级：DeepSeek → Gemini → pythainlp RTGS（本地兜底）

    音调标记规则（标在主元音上）：
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

    input_json = json.dumps([t for _, t in indexed], ensure_ascii=False)
    prompt = (
        "You are a Thai phonetics expert. Romanize each Thai string with tone marks on the main vowel:\n"
        "  mid=no mark, low=grave(à), falling=circumflex(â), high=acute(á), rising=caron(ǎ)\n"
        "Use hyphens between syllables; keep words separated by spaces.\n"
        "Return ONLY a JSON array of strings in the same order as the input. No explanation.\n\n"
        f"Input: {input_json}"
    )

    def _parse_romanized(content):
        m = re.search(r"\[.*\]", content, re.DOTALL)
        if not m:
            raise ValueError(f"no JSON array in response: {content[:200]}")
        romanized = json.loads(m.group())
        if not isinstance(romanized, list) or len(romanized) != len(indexed):
            raise ValueError(f"unexpected array length: got {len(romanized)}, expected {len(indexed)}")
        return romanized

    def _map_out(romanized):
        out = [""] * len(texts)
        for (orig_i, _), rom in zip(indexed, romanized):
            out[orig_i] = rom if isinstance(rom, str) else ""
        return out

    # ── DeepSeek（首选） ─────────────────────────────────────────
    try:
        from ai.provider import deepseek as deepseek_provider
        content = deepseek_provider.chat(prompt, temperature=0.1, timeout=30)
        romanized = _parse_romanized(content)
        logger.info(f"[romanize] th DeepSeek OK: {len(indexed)} segments")
        return _map_out(romanized)
    except Exception as e:
        logger.warning(f"[romanize] th DeepSeek failed ({e}), falling back to Gemini")

    # ── Gemini（降级） ───────────────────────────────────────────
    try:
        from ai.provider import gemini as gemini_provider
        result = gemini_provider.request(
            providers.Gemini.ROMANIZE_MODEL,
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1},
            },
            timeout=30,
            max_retries=2,
            tag="Romanize-TH",
        )
        content = result["candidates"][0]["content"]["parts"][0]["text"].strip()
        romanized = _parse_romanized(content)
        logger.info(f"[romanize] th Gemini OK: {len(indexed)} segments")
        return _map_out(romanized)
    except Exception as e:
        logger.warning(f"[romanize] th Gemini failed ({e}), falling back to pythainlp RTGS")

    # ── pythainlp RTGS（本地兜底） ────────────────────────────────
    all_rtgs = _romanize_th_pythainlp(texts)
    non_empty = sum(1 for x in all_rtgs if x)
    logger.info(f"[romanize] pythainlp RTGS: {non_empty}/{len(texts)} segments romanized")
    return all_rtgs


def generate_romanization(segments, language):
    """
    为 segments 列表中每个 Segment 写入 romanization 字段。

    Args:
        segments: list of Segment（domain.Segment 对象）
        language: Whisper 返回的语言代码，如 "th" / "zh" / "en"

    不支持的语言直接返回，不修改 segments。
    """
    lang = (language or "").lower()[:2]

    if lang == "zh":
        for seg in segments:
            text = seg.text.strip()
            seg.romanization = _romanize_zh(text) if text else ""

    elif lang == "th":
        texts = [seg.text.strip() for seg in segments]
        romanized = _romanize_th_batch(texts)
        for seg, rom in zip(segments, romanized):
            seg.romanization = rom

    # 其他语言（英/日/韩等）：不修改 romanization 字段
