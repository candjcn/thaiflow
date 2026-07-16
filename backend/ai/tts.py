"""
TTS 课程生成服务层
文本 → 语音课程：Gemini 分句标注 → 逐句 TTS（Gemini/Azure/Youdao）
→ ffmpeg 拼接 → 精确时间戳 segments

保持与原 tts.py 完全相同的公开函数签名和返回格式。
"""
import base64
import json
import os
import re
import struct
import subprocess
import tempfile

from config import providers, settings, get_logger
from ai.provider import gemini as gemini_provider
from ai.provider import deepseek as deepseek_provider
from ai.provider import azure as azure_provider
from ai.provider.youdao import YoudaoTTS

logger = get_logger(__name__)

# URL 模板（供内部使用）
GEMINI_URL      = gemini_provider.URL_V1
GEMINI_URL_BETA = gemini_provider.URL_V1BETA

# Gemini 预置声音（多语言通用）
GEMINI_VOICES = {
    "female_a": "Kore",    # 女声 A：沉稳
    "female_b": "Leda",    # 女声 B：年轻
    "male_a":   "Puck",    # 男声 A：明快
    "male_b":   "Charon",  # 男声 B：低沉
}

# Azure 神经声音
AZURE_VOICES = {
    "th": {"female_a": "th-TH-PremwadeeNeural", "female_b": "th-TH-AcharaNeural",
           "male_a":   "th-TH-NiwatNeural",     "male_b":   "th-TH-NiwatNeural"},
    "en": {"female_a": "en-US-JennyNeural",      "female_b": "en-US-AriaNeural",
           "male_a":   "en-US-GuyNeural",         "male_b":   "en-US-DavisNeural"},
    "zh": {"female_a": "zh-CN-XiaoxiaoNeural",   "female_b": "zh-CN-XiaoyiNeural",
           "male_a":   "zh-CN-YunxiNeural",       "male_b":   "zh-CN-YunjianNeural"},
    "ja": {"female_a": "ja-JP-NanamiNeural",      "female_b": "ja-JP-MayuNeural",
           "male_a":   "ja-JP-KeitaNeural",        "male_b":   "ja-JP-DaichiNeural"},
    "ko": {"female_a": "ko-KR-SunHiNeural",       "female_b": "ko-KR-JiMinNeural",
           "male_a":   "ko-KR-InJoonNeural",       "male_b":   "ko-KR-HyunsuNeural"},
}


# ========== 第一步：分句 + 说话人/性别/情感标注 ==========

# ========== 输入格式检测 ==========

_TARGET_LANG_SCRIPT = {
    "中文": "zh", "繁體中文": "zh",
    "English": "en",
    "日本語": "ja",
    "한국어": "ko",
    "ไทย": "th",
}

# ── 角色标签识别 ──────────────────────────────────────────────────────────────

_ROLE_LABEL_RE = re.compile(
    r'^([A-Za-z\u4e00-\u9fff\u0e00-\u0e7f]{1,10})[：:]\s*(.+)$'
)

_MALE_ROLES = {
    "男", "男生", "男方", "男声", "男士", "男人", "男孩", "男同学",
    "ชาย", "ผู้ชาย", "นาย",
    "male", "man", "boy", "m",
}
_FEMALE_ROLES = {
    "女", "女生", "女方", "女声", "女士", "女人", "女孩", "女同学",
    "หญิง", "ผู้หญิง", "นาง", "นางสาว",
    "female", "woman", "girl", "f",
}
_NARRATOR_ROLES = {"n", "旁白", "旁述", "narrator", "narration"}


def _parse_role_label(line):
    """检测行首角色标签，返回 (role_name, text_without_label) 或 None。"""
    m = _ROLE_LABEL_RE.match(line.strip())
    if not m:
        return None
    role, text = m.group(1).strip(), m.group(2).strip()
    return (role, text) if text else None


def _role_to_speaker_gender(role, role_map):
    """
    根据角色名推断 (speaker, gender)，同名角色保持一致。
    role_map: {role_name: (speaker, gender)}  — 跨行共享，原地修改
    """
    if role in role_map:
        return role_map[role]

    rl = role.lower()

    if rl in _NARRATOR_ROLES:
        result = ("N", "female")
    elif rl in _MALE_ROLES:
        # 第一个男声用 B，第二个也暂时用 B（不超过两声道）
        result = ("B", "male")
    elif rl in _FEMALE_ROLES:
        result = ("A", "female")
    elif len(role) == 1 and role.upper().isalpha():
        # 单字母：A→女A，B→男B，C→女A，D→男B …
        idx = ord(role.upper()) - ord("A")
        gender = "male" if idx % 2 == 1 else "female"
        speaker = role.upper() if role.upper() in ("A", "B") else ("B" if gender == "male" else "A")
        result = (speaker, gender)
    else:
        # 未知角色名：按出现顺序交替
        n = len(role_map)
        result = ("B", "male") if n % 2 == 1 else ("A", "female")

    role_map[role] = result
    return result


def _has_script(text, script):
    """检测文本是否含有指定脚本的字符"""
    patterns = {
        "th": r"[\u0e00-\u0e7f]",
        "zh": r"[\u4e00-\u9fff]",
        "ja": r"[\u3040-\u30ff\u4e00-\u9fff]",
        "ko": r"[\uac00-\ud7af]",
        "en": r"[a-zA-Z]",
    }
    p = patterns.get(script)
    return bool(re.search(p, text)) if p else False


def _guess_language(text):
    """从字符集猜测语言。双语文本先剥去括号内的译文，避免被译文字符误导。"""
    # 去掉括号内容（圆括号/方括号/中文括号，通常是译文）
    clean = re.sub(
        r'[\u0028\uff08\u3010\u005b][^\u0029\uff09\u3011\u005d]{1,100}[\u0029\uff09\u3011\u005d]',
        '', text
    ).strip() or text
    if re.search(r"[\u0e00-\u0e7f]", clean): return "th"
    if re.search(r"[\u3040-\u30ff]",  clean): return "ja"
    if re.search(r"[\uac00-\ud7af]",  clean): return "ko"
    if re.search(r"[\u4e00-\u9fff]",  clean): return "zh"
    return "en"  # 拉丁字母（英/西/法/德…），字符集无法区分


def detect_language_api(text):
    """对字符集无法区分的拉丁语系文本，用 Gemini 检测实际语言，返回 ISO 639-1 码。
    失败时返回 'en' 作为兜底。
    """
    snippet = text[:200].strip()
    try:
        result = gemini_provider.request(
            providers.Gemini.TEXT_MODEL,
            {"contents": [{"parts": [{"text": (
                "What language is the following text written in? "
                "Reply with ONLY the ISO 639-1 two-letter code (e.g. en, es, fr, de, th, zh, ja, ko). "
                "No explanation.\n\n" + snippet
            )}]}],
             "generationConfig": {"temperature": 0, "maxOutputTokens": 5}},
            timeout=8, tag="LangDetect",
        )
        code = result["candidates"][0]["content"]["parts"][0]["text"].strip().lower()[:2]
        return code if re.match(r'^[a-z]{2}$', code) else "en"
    except Exception as e:
        logger.warning(f"[LangDetect] Gemini 检测失败: {e}")
        return "en"


def _split_bilingual_line(line, src_script, tgt_script):
    """
    尝试把"原文 译文"同行拆成 (original, translation)。
    失败返回 None。
    优先级：括号包裹译文 > 字符集边界 > 多空格/Tab > 分隔符 > 单空格（仅短词）
    """
    _script_pat = {
        "th": r"[\u0e00-\u0e7f]",
        "zh": r"[\u4e00-\u9fff\uff00-\uffef]",
        "ja": r"[\u3040-\u30ff\u4e00-\u9fff]",
        "ko": r"[\uac00-\ud7af]",
        "en": r"[a-zA-Z]",
    }

    # ── 最高优先级：行尾各种括号包裹的译文 ──────────────────────
    # 支持：圆括号 ()（）、方括号 []【】
    m = re.search(r'[\u0028\uff08\u3010\u005b]([^\u0029\uff09\u3011\u005d]+)[\u0029\uff09\u3011\u005d]\s*$', line)
    if m:
        translation = m.group(1).strip()
        original = line[:m.start()].strip()
        if original and translation:
            return (original, translation)

    # ── 按字符集边界切分 ─────────────────────────────────────
    # 找第一个目标脚本字符位置，前段为源语言，后段为目标语言
    tgt_pat = _script_pat.get(tgt_script)
    if tgt_pat:
        m = re.search(tgt_pat, line)
        if m and m.start() > 0:
            a, b = line[:m.start()].strip(), line[m.start():].strip()
            if a and b and _has_script(a, src_script):
                return (a, b)

    # 反向：目标语在前，源语在后
    src_pat = _script_pat.get(src_script)
    if src_pat:
        m = re.search(src_pat, line)
        if m and m.start() > 0:
            a, b = line[:m.start()].strip(), line[m.start():].strip()
            if a and b and _has_script(a, tgt_script):
                return (b, a)

    # ── 后备：显式分隔符 ─────────────────────────────────────
    for pattern in (r"\s{2,}|\t", r"\s+-\s+|\s+—\s+|\s+–\s+"):
        parts = re.split(pattern, line, maxsplit=1)
        if len(parts) == 2:
            a, b = parts[0].strip(), parts[1].strip()
            if a and b:
                if _has_script(a, src_script) and _has_script(b, tgt_script):
                    return (a, b)
                if _has_script(b, src_script) and _has_script(a, tgt_script):
                    return (b, a)

    # ── 最后：单空格（仅适用于短词对如 "เงินสด 现金"）────────
    parts = line.split(None, 1)
    if len(parts) == 2:
        a, b = parts[0].strip(), parts[1].strip()
        if a and b:
            if _has_script(a, src_script) and not _has_script(a, tgt_script) \
                    and _has_script(b, tgt_script) and not _has_script(b, src_script):
                return (a, b)
            if _has_script(b, src_script) and not _has_script(b, tgt_script) \
                    and _has_script(a, tgt_script) and not _has_script(a, src_script):
                return (b, a)
    return None


def detect_input_mode(text, source_lang, target_lang):
    """
    检测用户输入格式，返回解析结果。

    三种模式：
      "bilingual"  — 每行含原文+译文，可跳过翻译 API
      "per_line"   — 每行一句/一词，可跳过 AI 分句
      "paragraph"  — 整段文本，走原有 AI 分句流程

    每个 item 可含 speaker / gender 字段（从角色标签解析而来）。
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # 单行 → 段落模式
    if len(lines) < 2:
        return {"mode": "paragraph", "items": [], "language": source_lang}

    src_lang = source_lang if source_lang != "auto" else _guess_language(lines[0])
    src_script = src_lang[:2].lower()
    tgt_script = _TARGET_LANG_SCRIPT.get(target_lang, "zh")

    # 先剥角色标签，保留角色信息供后续使用
    role_map = {}
    parsed_lines = []   # [{"raw": line, "text": content, "speaker": ..., "gender": ...}]
    for line in lines:
        role_result = _parse_role_label(line)
        if role_result:
            role_name, content = role_result
            speaker, gender = _role_to_speaker_gender(role_name, role_map)
            parsed_lines.append({"raw": line, "text": content,
                                  "speaker": speaker, "gender": gender})
        else:
            parsed_lines.append({"raw": line, "text": line,
                                  "speaker": None, "gender": None})

    content_lines = [p["text"] for p in parsed_lines]

    # ── 尝试双语模式 ─────────────────────────────────────────────
    if src_script != tgt_script:
        bilingual = []
        for p in parsed_lines:
            result = _split_bilingual_line(p["text"], src_script, tgt_script)
            if result:
                item = {"text": result[0], "translation": result[1]}
                if p["speaker"]:
                    item["speaker"] = p["speaker"]
                    item["gender"]  = p["gender"]
                bilingual.append(item)
            else:
                bilingual = None
                break
        if bilingual and len(bilingual) >= 2:
            logger.info(f"[InputMode] bilingual: {len(bilingual)} 行，跳过分句+翻译")
            return {"mode": "bilingual", "items": bilingual, "language": src_lang}

    # 有超长行（非双语）→ 段落模式
    if max(len(l) for l in lines) > 150:
        return {"mode": "paragraph", "items": [], "language": source_lang}

    # ── 逐行模式：平均行长 < 80 字符 ────────────────────────────
    avg_len = sum(len(l) for l in content_lines) / len(content_lines)
    if avg_len < 80:
        items = []
        for p in parsed_lines:
            # 逐行也尝试双语拆分：成功则只取源语言为 text，译文放 translation
            # 避免把整行（含中文/日文）整个送去 TTS
            translation = ""
            tts_text = p["text"]
            if src_script != tgt_script:
                split = _split_bilingual_line(p["text"], src_script, tgt_script)
                if split:
                    tts_text, translation = split[0], split[1]
            item = {"text": tts_text, "translation": translation}
            if p["speaker"]:
                item["speaker"] = p["speaker"]
                item["gender"]  = p["gender"]
            items.append(item)
        logger.info(f"[InputMode] per_line: {len(items)} 行，跳过 AI 分句")
        return {"mode": "per_line", "items": items, "language": src_lang}

    return {"mode": "paragraph", "items": [], "language": source_lang}


def _parse_script_json(raw):
    """从模型返回文本中提取并解析分句 JSON。"""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def prepare_script(text, language="th"):
    """把整段文本拆成句子并标注说话人/性别/情感。
    优先用 Gemini，失败时自动降级到 DeepSeek。
    返回 (script, detected_language)
    script: [{text, speaker, gender, emotion}, ...]
    """
    LANG_NAMES = {"th": "Thai", "en": "English", "zh": "Chinese", "ja": "Japanese", "ko": "Korean"}
    if language == "auto":
        lang_line = "0. Detect the main language of the text (two-letter ISO code like th/en/zh/ja/ko).\n"
        lang_desc = "the following"
    else:
        lang_line = ""
        lang_desc = LANG_NAMES.get(language, "the following")
    prompt = (
        f"Analyze this {lang_desc} text for a language-learning audio lesson.\n"
        + lang_line +
        "1. Split it into natural spoken sentences.\n"
        "   - For Thai: the spaces already present in the source text are the author's "
        "phrase boundaries — they are the ONLY candidate split points. Split at them to "
        "form natural sentences, MERGING short fragments (titles, names like "
        "พล.ต.ต.xxx, connective phrases) with their neighbors so each item is a "
        "meaningful spoken unit. Do not split inside a space-free run unless it "
        "exceeds ~60 characters.\n"
        "   - For other languages: split at sentence punctuation; break overly long "
        "sentences at natural clause boundaries.\n"
        "   - Never return the whole passage as one giant sentence.\n"
        "2. Detect if it is a dialogue. If yes, assign speakers \"A\" and \"B\" "
        "(alternating logically). For narration/story use speaker \"N\".\n"
        "3. Determine each speaker's gender from context. For Thai: sentence-final "
        "particles ครับ/ครับผม indicate a MALE speaker; ค่ะ/คะ/นะคะ indicate FEMALE. "
        "If unclear, alternate female for A / male for B; narrator defaults to female.\n"
        "4. Give each sentence a short English emotion/style hint matching the content "
        "(e.g. \"warm storytelling\", \"cheerful greeting\", \"curious question\", "
        "\"calm explanation\").\n"
        "Do NOT change, translate, or correct the text itself; strip only redundant "
        "speaker labels like \"A:\" if present.\n"
        "Return ONLY a JSON object: "
        '{"language": "th", "sentences": [{"text": "...", "speaker": "A", "gender": "female", "emotion": "..."}]}\n\n'
        + text
    )

    # ── DeepSeek（首选） ─────────────────────────────────────────────
    raw = None
    split_provider = None
    try:
        raw = deepseek_provider.chat(prompt, temperature=0, timeout=settings.TIMEOUT_TTS_SPLIT)
        split_provider = "deepseek"
        logger.info("[TTS] 分句: DeepSeek OK")
    except Exception as e:
        logger.warning(f"[TTS] 分句 DeepSeek 失败 ({e})，降级到 Gemini")

    # ── Gemini（降级） ───────────────────────────────────────────────
    if raw is None:
        result = gemini_provider.request(
            providers.Gemini.TEXT_MODEL,
            {"contents": [{"parts": [{"text": prompt}]}],
             "generationConfig": {"temperature": 0}},
            timeout=settings.TIMEOUT_GEMINI_DEFAULT, tag="Gemini分句",
        )
        raw = result["candidates"][0]["content"]["parts"][0]["text"]
        split_provider = "gemini"
        logger.info("[TTS] 分句: Gemini OK")

    parsed = _parse_script_json(raw)
    if isinstance(parsed, dict):
        items    = parsed.get("sentences", [])
        detected = (parsed.get("language") or "")[:2].lower()
    else:
        items    = parsed
        detected = ""
    if language != "auto":
        detected = language
    elif detected not in ("th", "en", "zh", "ja", "ko"):
        detected = "en"

    script = []
    for it in items:
        t = (it.get("text") or "").strip()
        if not t:
            continue
        script.append({
            "text":    t,
            "speaker": it.get("speaker", "N"),
            "gender":  "male" if str(it.get("gender", "")).lower().startswith("m") else "female",
            "emotion": it.get("emotion", "natural"),
        })
    if not script:
        raise RuntimeError("分句结果为空")

    script = _split_long_sentences(script, detected)

    speakers = {it["speaker"] for it in script}
    if "A" in speakers and "B" in speakers:
        a_genders = [it["gender"] for it in script if it["speaker"] == "A"]
        b_genders = [it["gender"] for it in script if it["speaker"] == "B"]
        ga = max(set(a_genders), key=a_genders.count)
        gb = max(set(b_genders), key=b_genders.count)
        if ga == gb:
            flipped = "male" if ga == "female" else "female"
            for it in script:
                if it["speaker"] == "B":
                    it["gender"] = flipped
        for it in script:
            if it["speaker"] == "A":
                it["gender"] = ga

    return script, detected, split_provider


def _split_long_sentences(script, language):
    """保底拆分：分句结果里仍有超长句时，再让 Gemini 按语义子句强拆。"""
    MAX_CHARS = 100
    MAX_WORDS = 28

    def too_long(t):
        if " " in t:
            return len(t.split()) > MAX_WORDS
        return len(t) > MAX_CHARS

    long_idx = [i for i, it in enumerate(script) if too_long(it["text"])]
    if not long_idx:
        return script

    lang_name = {"th": "Thai", "en": "English", "zh": "Chinese",
                 "ja": "Japanese", "ko": "Korean"}.get(language, "")
    texts    = [script[i]["text"] for i in long_idx]
    numbered = "\n".join(f"{i}\t{t}" for i, t in enumerate(texts))
    prompt = (
        f"Each numbered line below is a long {lang_name} sentence (index TAB text).\n"
        "Split EACH into shorter spoken chunks of at most ~10 words "
        "(~50 characters for Thai/Chinese/Japanese), cutting ONLY at natural "
        "clause boundaries. Do NOT change, add, remove, or reorder any characters.\n"
        "Return ONLY a JSON array of arrays: element i is the ordered list of "
        "chunks for input line i.\n\n" + numbered
    )
    raw = None
    try:
        raw = deepseek_provider.chat(prompt, temperature=0, timeout=settings.TIMEOUT_TTS_SPLIT)
    except Exception as e:
        logger.warning(f"[SplitLong] DeepSeek 失败 ({e})，降级到 Gemini")
    if raw is None:
        try:
            result = gemini_provider.request(
                providers.Gemini.TEXT_MODEL,
                {"contents": [{"parts": [{"text": prompt}]}],
                 "generationConfig": {"temperature": 0}},
                timeout=settings.TIMEOUT_GEMINI_DEFAULT, tag="长句拆分",
            )
            raw = result["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            logger.warning(f"[SplitLong] Gemini 也失败，保留原句: {e}")
            return script
    try:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        chunk_lists = json.loads(raw)
    except Exception as e:
        logger.warning(f"[SplitLong] 解析失败，保留原句: {e}")
        return script

    new_script = []
    for i, it in enumerate(script):
        if i in long_idx:
            pos    = long_idx.index(i)
            chunks = chunk_lists[pos] if pos < len(chunk_lists) else None
            if (isinstance(chunks, list) and len(chunks) > 1 and
                    "".join(chunks).replace(" ", "") == it["text"].replace(" ", "")):
                for c in chunks:
                    c = c.strip()
                    if c:
                        new_script.append({**it, "text": c})
                continue
        new_script.append(it)
    return new_script


# ========== 第二步：逐句 TTS ==========

def _voice_slot(speaker, gender):
    suffix = "_b" if speaker == "B" else "_a"
    return gender + suffix


def _pcm_to_wav(pcm_bytes, sample_rate=24000):
    """Gemini 返回裸 PCM（16-bit 单声道），包上 WAV 头"""
    data_len = len(pcm_bytes)
    header   = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_len, b"WAVE", b"fmt ", 16,
        1, 1, sample_rate, sample_rate * 2, 2, 16,
        b"data", data_len,
    )
    return header + pcm_bytes


def gemini_tts_sentence(text, voice_slot, emotion, out_path):
    """Gemini TTS 生成单句，带情感指令（内置限流/高负载重试）"""
    model  = providers.Gemini.TTS_MODEL
    voice  = GEMINI_VOICES.get(voice_slot, "Kore")
    styled = f"Say in a {emotion} tone: {text}" if emotion else text
    result = gemini_provider.request(model, {
        "contents": [{"parts": [{"text": styled}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
            },
        },
    }, timeout=settings.TIMEOUT_GEMINI_TTS, tag="GeminiTTS", url_tpl=GEMINI_URL_BETA)
    parts  = result["candidates"][0]["content"]["parts"]
    inline = next((p["inlineData"] for p in parts if "inlineData" in p), None)
    if inline is None:
        raise RuntimeError("Gemini TTS 返回中没有音频")
    pcm = base64.b64decode(inline["data"])
    with open(out_path, "wb") as f:
        f.write(_pcm_to_wav(pcm, 24000))


def azure_tts_sentence(text, voice_slot, language, out_path):
    """Azure Neural TTS 生成单句（24kHz WAV）"""
    voices = AZURE_VOICES.get(language, AZURE_VOICES["en"])
    voice  = voices.get(voice_slot, list(voices.values())[0])
    azure_provider.tts(text, voice, out_path)


def _wav_duration(path):
    """16-bit 单声道 WAV 时长（秒）"""
    with open(path, "rb") as f:
        header = f.read(44)
        sr     = struct.unpack("<I", header[24:28])[0]
        f.seek(0, 2)
        data_len = f.tell() - 44
    return data_len / (sr * 2)


# ========== 图片 OCR（Gemini 视觉）==========

def ocr_image(image_bytes, mime_type="image/png", language=""):
    """识别图片中的文字（隐藏测试功能）"""
    model     = providers.Gemini.TEXT_MODEL
    lang_name = {"th": "Thai", "en": "English"}.get((language or "")[:2].lower(), "")
    lang_hint = f"The text is mainly in {lang_name}. " if lang_name else ""
    prompt    = (
        f"{lang_hint}Extract ALL text from this image verbatim, preserving line breaks "
        "and dialogue structure. Output ONLY the extracted text, no explanations, "
        "no labels. If there is no text, output nothing."
    )
    result = gemini_provider.request(model, {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime_type,
                                 "data": base64.b64encode(image_bytes).decode()}},
            ]
        }],
        "generationConfig": {"temperature": 0},
    }, timeout=settings.TIMEOUT_GEMINI_DEFAULT, tag="OCR")
    parts = result["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts).strip()


# ========== 封面插画（Gemini 图片生成）==========

def _save_cover_image(img_bytes, out_path):
    """将图片字节保存为 512×512 JPEG。"""
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(img_bytes))
        img = img.resize((512, 512), Image.LANCZOS)
        img.save(out_path, "JPEG", quality=82, optimize=True)
    except Exception:
        with open(out_path, "wb") as f:
            f.write(img_bytes)


_LANG_META = {
    "th": ("Thai",    "Thailand",  "Thai street food stall, golden temple, tuk-tuk"),
    "zh": ("Chinese", "China",     "Chinese tea house, lanterns, traditional courtyard"),
    "ja": ("Japanese","Japan",     "Japanese izakaya, cherry blossoms, tatami room"),
    "ko": ("Korean",  "Korea",     "Korean cafe, hanbok, night market street"),
    "fr": ("French",  "France",    "Parisian café, Eiffel Tower, French bakery"),
    "de": ("German",  "Germany",   "German market, cozy pub, autumn forest"),
    "es": ("Spanish", "Spain",     "Spanish plaza, flamenco, tapas bar"),
}


def _cover_image_prompt(text, language):
    """把任意语言文本转为 flux-1-schnell 可理解的英文 image prompt。
    英文直接构建；其他语言先用 Gemini Flash 生成带文化背景的英文场景描述。
    """
    text_snippet = text[:300].strip()

    if language == "en":
        scene = (
            f"A language learner studying English: {text_snippet[:120]}. "
            "Cozy study setting with books and warm lighting."
        )
    else:
        meta = _LANG_META.get(language)
        lang_name    = meta[0] if meta else language.upper()
        country_name = meta[1] if meta else ""
        culture_hint = meta[2] if meta else ""

        gemini_prompt = (
            f"You are creating a cover image for a {lang_name} language lesson in a learning app.\n"
            f"The lesson content (in {lang_name}) is:\n\n{text_snippet}\n\n"
            f"Write ONE vivid English scene description (15–25 words) for an illustration that:\n"
            f"- Captures the topic or mood of this lesson\n"
            f"- Includes a recognizable {country_name} cultural visual element "
            f"(e.g. {culture_hint})\n"
            f"- Feels warm, inviting, and suitable for a language learner\n"
            f"Output ONLY the scene description, no explanation."
        )
        try:
            result = gemini_provider.request(
                providers.Gemini.TEXT_MODEL,
                {"contents": [{"parts": [{"text": gemini_prompt}]}],
                 "generationConfig": {"temperature": 0.7, "maxOutputTokens": 80}},
                timeout=settings.TIMEOUT_TTS_COVER_PROMPT, tag="CoverPrompt",
            )
            scene = result["candidates"][0]["content"]["parts"][0]["text"].strip()
            logger.info(f"[Cover] 场景描述: {scene!r}")
        except Exception as e:
            logger.warning(f"[Cover] Gemini 场景描述失败 ({e})，使用默认场景")
            scene = (
                f"A student learning {lang_name} in a cozy {country_name} café, "
                f"textbook open, warm afternoon light."
            )

    return (
        f"Flat-design cartoon illustration: {scene} "
        "Soft pastel colors, clean lines, warm cozy atmosphere. "
        "No text, no letters, no words anywhere in the image."
    )


def generate_cover_image(text, language, out_path):
    """根据文本内容生成卡通风格封面插画。
    优先用 Cloudflare Workers AI（免费），失败降级到 Gemini。
    失败时返回 False，不影响主流程。
    """
    prompt = _cover_image_prompt(text, language)

    # ── Cloudflare Workers AI（首选，免费） ──────────────────────
    try:
        from ai.provider import cloudflare as cf_provider
        img_bytes = cf_provider.generate_image(prompt, timeout=settings.TIMEOUT_CF_IMAGE)
        _save_cover_image(img_bytes, out_path)
        logger.info("[Cover] Cloudflare Workers AI OK")
        return True
    except Exception as e:
        logger.warning(f"[Cover] Cloudflare 失败 ({e})，降级到 Gemini")

    # ── Gemini（降级） ───────────────────────────────────────────
    try:
        result = gemini_provider.request(providers.Gemini.IMAGE_MODEL, {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }, timeout=settings.TIMEOUT_GEMINI_COVER, max_retries=2,
            tag="Cover", url_tpl=GEMINI_URL_BETA)
        for part in result["candidates"][0]["content"]["parts"]:
            inline = part.get("inlineData")
            if inline and inline.get("mimeType", "").startswith("image/"):
                img_bytes = base64.b64decode(inline["data"])
                _save_cover_image(img_bytes, out_path)
                logger.info("[Cover] Gemini OK")
                return True
        logger.warning("[Cover] Gemini 返回中没有图片")
        return False
    except Exception as e:
        logger.warning(f"[Cover] Gemini 也失败: {e}")
        return False


# ========== 第三步：拼接 + 时间戳 ==========

GAP_SEC = 0.4  # 句间停顿


def generate_audio_lesson(text, language, engine, out_dir, progress=None, pre_items=None):
    """完整流程：文本 → 音频文件 + segments。
    返回 (audio_filename, segments, detected_language, meta)
    meta: {"split_provider": str}

    pre_items: [{"text": str, "translation": str}, ...] — 已解析好的条目，跳过 AI 分句
    """
    def report(msg):
        if progress:
            progress(msg)

    if pre_items is not None:
        # 逐行/双语模式：直接构建 script，跳过 AI 分句
        report("正在准备文本...")
        has_dialogue = any(item.get("speaker") in ("A", "B") for item in pre_items)
        script = []
        for item in pre_items:
            t = item["text"].strip()
            if not t:
                continue
            if has_dialogue:
                speaker = item.get("speaker") or "N"
                gender  = item.get("gender")  or "female"
            else:
                speaker, gender = "N", "female"
            script.append({"text": t, "speaker": speaker,
                           "gender": gender, "emotion": "natural"})
        if not script:
            raise RuntimeError("文本内容为空")
        script = _split_long_sentences(script, language)
        meta = {"split_provider": "skipped"}
    else:
        report("正在分析文本、分配角色...")
        script, language, split_provider = prepare_script(text, language)
        meta = {"split_provider": split_provider or "unknown"}

    _FALLBACK = {
        "gemini": ["gemini", "azure"],
        "azure":  ["azure", "gemini"],
        "youdao": ["youdao", "gemini", "azure"],
    }
    engine_queue   = _FALLBACK.get(engine, [engine, "azure"])
    tmpdir         = tempfile.mkdtemp(prefix="tts_")
    clips          = []
    youdao         = YoudaoTTS() if "youdao" in engine_queue else None
    current_engine = engine_queue[0]

    try:
        for i, item in enumerate(script):
            report(f"正在生成语音 {i + 1}/{len(script)}...")
            slot = _voice_slot(item["speaker"], item["gender"])
            clip = os.path.join(tmpdir, f"clip_{i:03d}.wav")

            tried     = set()
            remaining = [current_engine] + [e for e in engine_queue if e != current_engine]
            last_err  = None
            for eng in remaining:
                if eng in tried:
                    continue
                tried.add(eng)
                try:
                    if eng == "azure":
                        azure_tts_sentence(item["text"], slot, language, clip)
                    elif eng == "youdao" and youdao:
                        youdao.tts_sentence(item["text"], language, item["gender"], clip)
                    else:  # gemini
                        gemini_tts_sentence(item["text"], slot, item["emotion"], clip)
                    if eng != current_engine:
                        logger.info(f"[TTS] 第{i+1}句起自动切换至 {eng}（{current_engine} 失败）")
                        current_engine = eng
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    logger.warning(f"[TTS] {eng} 引擎第{i+1}句失败: {e}")

            if last_err:
                raise RuntimeError(f"所有 TTS 引擎均失败（第{i+1}句）: {last_err}")
            clips.append(clip)

        segments = []
        cursor   = 0.0
        for i, (item, clip) in enumerate(zip(script, clips)):
            dur = _wav_duration(clip)
            segments.append({
                "index": i,
                "text":  item["text"],
                "start": round(cursor, 2),
                "end":   round(cursor + dur, 2),
            })
            cursor += dur + GAP_SEC

        report("正在拼接音频...")
        silence   = os.path.join(tmpdir, "silence.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
             "-t", str(GAP_SEC), "-sample_fmt", "s16", silence],
            capture_output=True, check=True,
        )
        list_path = os.path.join(tmpdir, "list.txt")
        with open(list_path, "w") as f:
            for i, clip in enumerate(clips):
                f.write(f"file '{clip}'\n")
                if i < len(clips) - 1:
                    f.write(f"file '{silence}'\n")

        safe       = "".join(c for c in text[:16] if c.isalnum() or c in " ").strip() or "audio"
        import time as _time
        audio_name = f"朗读_{safe}_{int(_time.time()) % 100000}.m4a"
        out_path   = os.path.join(out_dir, audio_name)
        r = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
             "-c:a", "aac", "-b:a", "128k", out_path],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise RuntimeError("音频拼接失败: " + r.stderr[-200:])

        return audio_name, segments, language, meta
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def generate_tts_content(prompt: str, language: str) -> str:
    """AI 生成双语学习内容（对话 / 词汇列表）。

    Args:
        prompt:   用户要求（调用方已截断至合理长度）
        language: 目标语言代码（如 "th" / "zh" / "en"）

    Returns:
        格式化的双语内容文本，每行一句或一词。

    Raises:
        Exception: Provider 调用失败时向上抛出，由路由层处理。
    """
    system = (
        "你是语言学习内容生成专家。根据用户要求生成双语学习材料。\n"
        "输出格式规则（必须严格遵守）：\n"
        "- 对话：每行格式为「A: 外语原文（中文翻译）」或「B: 外语原文（中文翻译）」\n"
        "- 词汇：每行格式为「外语词汇/短语（中文翻译）」\n"
        "- 原文不加任何括号，译文用（）紧接在原文后括起来\n"
        "- 每行一句或一词，不加编号\n"
        "- 直接输出内容，不要有任何前言、后记或说明文字"
    )
    user_msg = f"目标语言：{language}\n用户要求：{prompt}"
    full_prompt = system + "\n\n" + user_msg

    if language == "zh":
        text = deepseek_provider.chat(
            full_prompt,
            temperature=0.7,
            timeout=settings.TIMEOUT_TTS_CONTENT,
        )
    else:
        result = gemini_provider.request(
            model=providers.Gemini.TEXT_MODEL,
            payload={
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": {"temperature": 0.7},
            },
            timeout=settings.TIMEOUT_TTS_CONTENT,
            tag="TTS-content",
        )
        text = result["candidates"][0]["content"]["parts"][0]["text"]

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)
