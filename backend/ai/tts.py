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
    """从字符集简单猜测语言"""
    if re.search(r"[\u0e00-\u0e7f]", text): return "th"
    if re.search(r"[\u3040-\u30ff]",  text): return "ja"
    if re.search(r"[\uac00-\ud7af]",  text): return "ko"
    if re.search(r"[\u4e00-\u9fff]",  text): return "zh"
    return "en"


def _split_bilingual_line(line, src_script, tgt_script):
    """
    尝试把"原文 译文"同行拆成 (original, translation)。
    失败返回 None。
    优先级：多空格/Tab > " - " / " — " > 单空格
    """
    for pattern in (r"\s{2,}|\t", r"\s+-\s+|\s+—\s+|\s+–\s+"):
        parts = re.split(pattern, line, maxsplit=1)
        if len(parts) == 2:
            a, b = parts[0].strip(), parts[1].strip()
            if a and b:
                if _has_script(a, src_script) and _has_script(b, tgt_script):
                    return (a, b)
                if _has_script(b, src_script) and _has_script(a, tgt_script):
                    return (b, a)

    # 最后试单个空格（适用于短词对如 "เงินสด 现金"）
    parts = line.split(None, 1)
    if len(parts) == 2:
        a, b = parts[0].strip(), parts[1].strip()
        if a and b:
            if _has_script(a, src_script) and _has_script(b, tgt_script):
                return (a, b)
            if _has_script(b, src_script) and _has_script(a, tgt_script):
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

    # 单行或有超长行 → 段落模式
    if len(lines) < 2 or max(len(l) for l in lines) > 150:
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

    # ── 逐行模式：平均行长 < 80 字符 ────────────────────────────
    avg_len = sum(len(l) for l in content_lines) / len(content_lines)
    if avg_len < 80:
        items = []
        for p in parsed_lines:
            item = {"text": p["text"], "translation": ""}
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
    try:
        raw = deepseek_provider.chat(prompt, temperature=0, timeout=60)
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

    return script, detected


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
        raw = deepseek_provider.chat(prompt, temperature=0, timeout=60)
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

def generate_cover_image(text, language, out_path):
    """根据文本内容生成卡通风格封面插画。失败时返回 False，不影响主流程。"""
    model     = providers.Gemini.IMAGE_MODEL
    lang_name = {"th": "Thai", "en": "English"}.get(language, "")
    prompt    = (
        "Create ONE simple, warm, flat-design cartoon illustration that captures "
        f"the scene or theme of this {lang_name} text. "
        "Style: minimalist flat cartoon, soft colors, cozy mood. "
        "Square 1:1 aspect ratio. "
        "Absolutely NO words, NO letters, NO text in the image.\n\n"
        + text[:400]
    )
    try:
        result = gemini_provider.request(model, {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }, timeout=settings.TIMEOUT_GEMINI_COVER, max_retries=2,
            tag="Cover", url_tpl=GEMINI_URL_BETA)
        for part in result["candidates"][0]["content"]["parts"]:
            inline = part.get("inlineData")
            if inline and inline.get("mimeType", "").startswith("image/"):
                img_bytes = base64.b64decode(inline["data"])
                try:
                    from PIL import Image
                    import io
                    img = Image.open(io.BytesIO(img_bytes))
                    img = img.resize((512, 512), Image.LANCZOS)
                    img.save(out_path, "JPEG", quality=82, optimize=True)
                except Exception:
                    with open(out_path, "wb") as f:
                        f.write(img_bytes)
                return True
        logger.warning("[Cover] 返回中没有图片")
        return False
    except Exception as e:
        logger.warning(f"[Cover] 生成失败: {e}")
        return False


# ========== 第三步：拼接 + 时间戳 ==========

GAP_SEC = 0.4  # 句间停顿


def generate_audio_lesson(text, language, engine, out_dir, progress=None, pre_items=None):
    """完整流程：文本 → 音频文件 + segments。
    返回 (audio_filename, segments, detected_language)

    pre_items: [{"text": str, "translation": str}, ...] — 已解析好的条目，跳过 AI 分句
    """
    def report(msg):
        if progress:
            progress(msg)

    if pre_items is not None:
        # 逐行/双语模式：直接构建 script，跳过 AI 分句
        report("正在准备文本...")
        # 如果有角色标签，A/B 对话模式；否则全部用旁白 N
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
    else:
        report("正在分析文本、分配角色...")
        script, language = prepare_script(text, language)

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

        return audio_name, segments, language
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
