"""
文本 → 语音课程生成
流程：Gemini 分句标注（说话人/性别/情感）→ 逐句 TTS（Gemini 或 Azure）
     → ffmpeg 拼接 → 精确时间戳 segments
"""
import base64
import json
import os
import struct
import subprocess
import tempfile

import requests

GEMINI_URL    = "https://generativelanguage.googleapis.com/v1/models/{model}:generateContent?key={key}"
GEMINI_URL_BETA = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

# Gemini 预置声音（多语言通用）
GEMINI_VOICES = {
    "female_a": "Kore",     # 女声 A：沉稳
    "female_b": "Leda",     # 女声 B：年轻
    "male_a": "Puck",       # 男声 A：明快
    "male_b": "Charon",     # 男声 B：低沉
}

# Azure 神经声音
AZURE_VOICES = {
    "th": {"female_a": "th-TH-PremwadeeNeural", "female_b": "th-TH-AcharaNeural",
           "male_a": "th-TH-NiwatNeural", "male_b": "th-TH-NiwatNeural"},
    "en": {"female_a": "en-US-JennyNeural", "female_b": "en-US-AriaNeural",
           "male_a": "en-US-GuyNeural", "male_b": "en-US-DavisNeural"},
    "zh": {"female_a": "zh-CN-XiaoxiaoNeural", "female_b": "zh-CN-XiaoyiNeural",
           "male_a": "zh-CN-YunxiNeural", "male_b": "zh-CN-YunjianNeural"},
    "ja": {"female_a": "ja-JP-NanamiNeural", "female_b": "ja-JP-MayuNeural",
           "male_a": "ja-JP-KeitaNeural", "male_b": "ja-JP-DaichiNeural"},
    "ko": {"female_a": "ko-KR-SunHiNeural", "female_b": "ko-KR-JiMinNeural",
           "male_a": "ko-KR-InJoonNeural", "male_b": "ko-KR-HyunsuNeural"},
}


def _gemini_key():
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("请配置 GEMINI_API_KEY")
    return key


def _gemini_request(model, payload, timeout=60, max_retries=4, tag="Gemini", url_tpl=None):
    """统一的 Gemini 调用：429 限流和 503 高负载自动退避重试。
    url_tpl: 默认用 GEMINI_URL (v1)；预览模型传 GEMINI_URL_BETA (v1beta)。"""
    import time

    if url_tpl is None:
        url_tpl = GEMINI_URL
    last_err = ""
    attempts_made = 0
    for attempt in range(max_retries):
        attempts_made = attempt + 1
        try:
            resp = requests.post(
                url_tpl.format(model=model, key=_gemini_key()),
                json=payload, timeout=timeout,
            )
            if resp.status_code == 200:
                return resp.json()
            last_err = f"{resp.status_code}: {resp.text[:300]}"
            if resp.status_code == 429:
                wait = 15 * (attempt + 1)
                print(f"[{tag}] 限流，{wait}s 后重试（{attempt + 1}/{max_retries}）")
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                wait = 5 * (attempt + 1)
                print(f"[{tag}] 服务繁忙 {resp.status_code}，{wait}s 后重试（{attempt + 1}/{max_retries}）")
                time.sleep(wait)
                continue
            break  # 其他 4xx（含 404 模型不存在）不重试
        except requests.RequestException as e:
            last_err = str(e)[:300]
            time.sleep(3 * (attempt + 1))

    raise RuntimeError(f"{tag} 失败（尝试 {attempts_made} 次）{last_err}")


# ========== 第一步：分句 + 说话人/性别/情感标注 ==========

def prepare_script(text, language="th"):
    """用 Gemini 把整段文本拆成句子并标注。
    返回 [{text, speaker: "A"|"B"|"N", gender: "male"|"female", emotion}, ...]
    泰语性别线索：ครับ=男，ค่ะ/คะ=女。language="auto" 时自动检测语言。
    返回 (script, detected_language)"""
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
    model = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
    result = _gemini_request(model, {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0},
    }, timeout=60, tag="Gemini分句")
    raw = result["candidates"][0]["content"]["parts"][0]["text"].strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
    parsed = json.loads(raw)
    # 兼容两种返回：对象 {"language", "sentences"} 或纯数组
    if isinstance(parsed, dict):
        items = parsed.get("sentences", [])
        detected = (parsed.get("language") or "")[:2].lower()
    else:
        items = parsed
        detected = ""
    if language != "auto":
        detected = language
    elif detected not in ("th", "en", "zh", "ja", "ko"):
        detected = "en"  # 检测失败兜底

    script = []
    for it in items:
        t = (it.get("text") or "").strip()
        if not t:
            continue
        script.append({
            "text": t,
            "speaker": it.get("speaker", "N"),
            "gender": "male" if str(it.get("gender", "")).lower().startswith("m") else "female",
            "emotion": it.get("emotion", "natural"),
        })
    if not script:
        raise RuntimeError("分句结果为空")

    # 保底：仍存在超长句时，二次强制拆分
    script = _split_long_sentences(script, detected)

    # 对话场景：强制 A/B 一男一女，便于区分学习
    # （保留 A 检测到的性别，B 取相反性别）
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
        # 同一说话人内部保持一致
        for it in script:
            if it["speaker"] == "A":
                it["gender"] = ga

    return script, detected


def _split_long_sentences(script, language):
    """保底拆分：分句结果里仍有超长句时，再让 Gemini 按语义子句强拆。
    拆分后的子句继承原句的说话人/性别/情感；字符级校验失败则保留原句。"""
    # 仅兜底极端情况（正常自然长句不拆，避免硬性上限切碎语义）
    MAX_CHARS = 100  # 无空格文字（泰/中/日）
    MAX_WORDS = 28   # 有空格文字

    def too_long(t):
        if " " in t:
            return len(t.split()) > MAX_WORDS
        return len(t) > MAX_CHARS

    long_idx = [i for i, it in enumerate(script) if too_long(it["text"])]
    if not long_idx:
        return script

    lang_name = {"th": "Thai", "en": "English", "zh": "Chinese",
                 "ja": "Japanese", "ko": "Korean"}.get(language, "")
    texts = [script[i]["text"] for i in long_idx]
    numbered = "\n".join(f"{i}\t{t}" for i, t in enumerate(texts))
    prompt = (
        f"Each numbered line below is a long {lang_name} sentence (index TAB text).\n"
        "Split EACH into shorter spoken chunks of at most ~10 words "
        "(~50 characters for Thai/Chinese/Japanese), cutting ONLY at natural "
        "clause boundaries. Do NOT change, add, remove, or reorder any characters.\n"
        "Return ONLY a JSON array of arrays: element i is the ordered list of "
        "chunks for input line i.\n\n" + numbered
    )
    model = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
    try:
        result = _gemini_request(model, {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0},
        }, timeout=60, tag="长句拆分")
        raw = result["candidates"][0]["content"]["parts"][0]["text"].strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        chunk_lists = json.loads(raw)
    except Exception as e:
        print(f"[SplitLong] 拆分失败，保留原句: {e}")
        return script

    new_script = []
    for i, it in enumerate(script):
        if i in long_idx:
            pos = long_idx.index(i)
            chunks = chunk_lists[pos] if pos < len(chunk_lists) else None
            # 校验：拆分后拼回去（忽略空格）必须与原文一致
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
    """说话人 → 声音槽位：A/N 用 _a 声，B 用 _b 声"""
    suffix = "_b" if speaker == "B" else "_a"
    return gender + suffix


def _pcm_to_wav(pcm_bytes, sample_rate=24000):
    """Gemini 返回裸 PCM（16-bit 单声道），包上 WAV 头"""
    data_len = len(pcm_bytes)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_len, b"WAVE", b"fmt ", 16,
        1, 1, sample_rate, sample_rate * 2, 2, 16,
        b"data", data_len,
    )
    return header + pcm_bytes


def gemini_tts_sentence(text, voice_slot, emotion, out_path):
    """Gemini TTS 生成单句，带情感指令（内置限流/高负载重试）"""
    model = os.environ.get("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview")
    voice = GEMINI_VOICES.get(voice_slot, "Kore")
    styled = f"Say in a {emotion} tone: {text}" if emotion else text
    result = _gemini_request(model, {
        "contents": [{"parts": [{"text": styled}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
            },
        },
    }, timeout=120, tag="GeminiTTS", url_tpl=GEMINI_URL_BETA)
    parts = result["candidates"][0]["content"]["parts"]
    inline = next((p["inlineData"] for p in parts if "inlineData" in p), None)
    if inline is None:
        raise RuntimeError("Gemini TTS 返回中没有音频")
    pcm = base64.b64decode(inline["data"])
    with open(out_path, "wb") as f:
        f.write(_pcm_to_wav(pcm, 24000))


def azure_tts_sentence(text, voice_slot, language, out_path):
    """Azure Neural TTS 生成单句（16kHz WAV）"""
    import azure.cognitiveservices.speech as speechsdk

    key = os.environ.get("AZURE_SPEECH_KEY", "")
    region = os.environ.get("AZURE_SPEECH_REGION", "")
    if not key or not region:
        raise RuntimeError("请配置 AZURE_SPEECH_KEY/REGION")

    voices = AZURE_VOICES.get(language, AZURE_VOICES["en"])
    voice = voices.get(voice_slot, list(voices.values())[0])

    speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
    speech_config.speech_synthesis_voice_name = voice
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm
    )
    audio_config = speechsdk.audio.AudioOutputConfig(filename=out_path)
    synth = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    result = synth.speak_text_async(text).get()
    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        detail = ""
        if result.reason == speechsdk.ResultReason.Canceled:
            detail = result.cancellation_details.error_details
        raise RuntimeError(f"Azure TTS 失败: {detail}")


def _wav_duration(path):
    """16-bit 单声道 WAV 时长（秒）"""
    with open(path, "rb") as f:
        header = f.read(44)
        sr = struct.unpack("<I", header[24:28])[0]
        f.seek(0, 2)
        data_len = f.tell() - 44
    return data_len / (sr * 2)


# ========== 有道 Confucius TTS（Gradio 会话协议 + 声音克隆） ==========

YOUDAO_BASE = "https://confucius4-tts.youdao.com/gradio"
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
YOUDAO_REFS = {"male": "ref_thai_male.wav", "female": "ref_thai_female.wav"}


class YoudaoTTS:
    """有道子曰 TTS 演示端点。声音克隆：按性别用预置参考音频建会话，
    参考音频预处理一次后同会话内逐句合成。"""

    def __init__(self):
        self.sessions = {}  # gender -> (session_hash, file_data)

    def _run(self, session, fn_index, trigger_id, data, timeout=300):
        import secrets
        r = requests.post(f"{YOUDAO_BASE}/queue/join", json={
            "data": data, "event_data": None, "fn_index": fn_index,
            "trigger_id": trigger_id, "session_hash": session,
        }, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"有道 TTS 排队失败 {r.status_code}")
        with requests.get(f"{YOUDAO_BASE}/queue/data?session_hash={session}",
                          stream=True, timeout=timeout) as resp:
            for line in resp.iter_lines():
                if not line or not line.startswith(b"data:"):
                    continue
                msg = json.loads(line[5:].strip())
                if msg.get("msg") == "process_completed":
                    out = msg.get("output") or {}
                    if out.get("error"):
                        raise RuntimeError(f"有道 TTS 出错: {str(out['error'])[:150]}")
                    return out
        raise RuntimeError("有道 TTS 无响应（演示端点可能繁忙，请换 Gemini/Azure 引擎）")

    def _ensure_session(self, gender):
        import secrets
        if gender in self.sessions:
            return
        ref_file = os.path.join(ASSETS_DIR, YOUDAO_REFS.get(gender, YOUDAO_REFS["female"]))
        if not os.path.exists(ref_file):
            raise RuntimeError(f"缺少参考音频: {ref_file}")
        with open(ref_file, "rb") as f:
            r = requests.post(f"{YOUDAO_BASE}/upload",
                              files={"files": ("ref.wav", f, "audio/wav")}, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"参考音频上传失败 {r.status_code}")
        path = r.json()[0]
        fdata = {
            "path": path, "url": f"{YOUDAO_BASE}/file={path}",
            "orig_name": "ref.wav", "size": os.path.getsize(ref_file),
            "mime_type": "audio/wav", "meta": {"_type": "gradio.FileData"},
        }
        session = secrets.token_hex(8)
        self._run(session, 0, 6, [fdata], timeout=120)  # 触发参考音频预处理
        self.sessions[gender] = (session, fdata)

    def tts_sentence(self, text, language, gender, out_path):
        self._ensure_session(gender)
        session, fdata = self.sessions[gender]
        out = self._run(session, 1, 9, [text, language, fdata, None])
        data = out.get("data")
        if not data or not data[0]:
            raise RuntimeError(f"有道 TTS 合成失败: {str(data)[:120]}")
        audio = requests.get(data[0]["url"], timeout=60).content
        tmp = out_path + ".dl"
        with open(tmp, "wb") as f:
            f.write(audio)
        # 统一转 24kHz 单声道 16-bit WAV（便于拼接和时长计算）
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", tmp, "-ar", "24000", "-ac", "1",
             "-sample_fmt", "s16", out_path],
            capture_output=True, text=True,
        )
        os.remove(tmp)
        if r.returncode != 0:
            raise RuntimeError("有道音频转换失败: " + r.stderr[-150:])


# ========== 图片 OCR（Gemini 视觉，测试功能） ==========

def ocr_image(image_bytes, mime_type="image/png", language=""):
    """识别图片中的文字（隐藏测试功能：粘贴文本框支持直接贴图）"""
    model = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
    lang_name = {"th": "Thai", "en": "English"}.get((language or "")[:2].lower(), "")
    lang_hint = f"The text is mainly in {lang_name}. " if lang_name else ""
    prompt = (
        f"{lang_hint}Extract ALL text from this image verbatim, preserving line breaks "
        "and dialogue structure. Output ONLY the extracted text, no explanations, "
        "no labels. If there is no text, output nothing."
    )
    result = _gemini_request(model, {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime_type,
                                 "data": base64.b64encode(image_bytes).decode()}},
            ]
        }],
        "generationConfig": {"temperature": 0},
    }, timeout=60, tag="OCR")
    parts = result["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts).strip()


# ========== 封面插画（Gemini 图片生成） ==========

def generate_cover_image(text, language, out_path):
    """根据文本内容生成一张卡通风格封面插画。失败时返回 False，不影响主流程。"""
    model = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-lite-image")
    lang_name = {"th": "Thai", "en": "English"}.get(language, "")
    prompt = (
        "Create ONE simple, warm, flat-design cartoon illustration that captures "
        f"the scene or theme of this {lang_name} text. "
        "Style: minimalist flat cartoon, soft colors, cozy mood. "
        "Absolutely NO words, NO letters, NO text in the image.\n\n"
        + text[:400]
    )
    try:
        result = _gemini_request(model, {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }, timeout=90, max_retries=2, tag="Cover", url_tpl=GEMINI_URL_BETA)
        for part in result["candidates"][0]["content"]["parts"]:
            inline = part.get("inlineData")
            if inline and inline.get("mimeType", "").startswith("image/"):
                with open(out_path, "wb") as f:
                    f.write(base64.b64decode(inline["data"]))
                return True
        print("[Cover] 返回中没有图片")
        return False
    except Exception as e:
        print(f"[Cover] 生成失败: {e}")
        return False


# ========== 第三步：拼接 + 时间戳 ==========

GAP_SEC = 0.4  # 句间停顿


def generate_audio_lesson(text, language, engine, out_dir, progress=None):
    """完整流程：文本 → 音频文件 + segments。
    返回 (audio_filename, segments, detected_language)"""
    def report(msg):
        if progress:
            progress(msg)

    report("正在分析文本、分配角色...")
    script, language = prepare_script(text, language)  # auto 时得到检测语言

    # TTS 引擎回退顺序：首选引擎失败时自动切换
    _FALLBACK = {
        "gemini": ["gemini", "azure"],
        "azure":  ["azure", "gemini"],
        "youdao": ["youdao", "gemini", "azure"],
    }
    engine_queue = _FALLBACK.get(engine, [engine, "azure"])

    tmpdir = tempfile.mkdtemp(prefix="tts_")
    clips = []
    youdao = YoudaoTTS() if "youdao" in engine_queue else None
    current_engine = engine_queue[0]
    try:
        for i, item in enumerate(script):
            report(f"正在生成语音 {i + 1}/{len(script)}...")
            slot = _voice_slot(item["speaker"], item["gender"])
            clip = os.path.join(tmpdir, f"clip_{i:03d}.wav")

            # 逐引擎尝试，失败后切换并沿用到后续句子
            tried = set()
            remaining = [current_engine] + [e for e in engine_queue if e != current_engine]
            last_err = None
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
                        print(f"[TTS] 第{i+1}句起自动切换至 {eng}（{current_engine} 失败）")
                        current_engine = eng  # 后续句子也用新引擎
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    print(f"[TTS] {eng} 引擎第{i+1}句失败: {e}")

            if last_err:
                raise RuntimeError(f"所有 TTS 引擎均失败（第{i+1}句）: {last_err}")
            clips.append(clip)

        # 计算时间戳（含句间停顿）
        segments = []
        cursor = 0.0
        for i, (item, clip) in enumerate(zip(script, clips)):
            dur = _wav_duration(clip)
            segments.append({
                "index": i,
                "text": item["text"],
                "start": round(cursor, 2),
                "end": round(cursor + dur, 2),
            })
            cursor += dur + GAP_SEC

        # 生成句间静音 + concat 列表
        report("正在拼接音频...")
        silence = os.path.join(tmpdir, "silence.wav")
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

        # 文件名：取文本开头
        safe = "".join(c for c in text[:16] if c.isalnum() or c in " ") .strip() or "audio"
        import time as _time
        audio_name = f"朗读_{safe}_{int(_time.time()) % 100000}.m4a"
        out_path = os.path.join(out_dir, audio_name)
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
