"""
TTS 课程生成服务层
文本 → 语音课程：Gemini 分句标注 → 逐句 TTS（Gemini/Azure/Youdao）
→ ffmpeg 拼接 → 精确时间戳 segments

保持与原 tts.py 完全相同的公开函数签名和返回格式。
"""
import base64
import json
import os
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


def generate_audio_lesson(text, language, engine, out_dir, progress=None):
    """完整流程：文本 → 音频文件 + segments。
    返回 (audio_filename, segments, detected_language)
    """
    def report(msg):
        if progress:
            progress(msg)

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
