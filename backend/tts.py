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

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

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
}


def _gemini_key():
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("请配置 GEMINI_API_KEY")
    return key


# ========== 第一步：分句 + 说话人/性别/情感标注 ==========

def prepare_script(text, language="th"):
    """用 Gemini 把整段文本拆成句子并标注。
    返回 [{text, speaker: "A"|"B"|"N", gender: "male"|"female", emotion}, ...]
    泰语性别线索：ครับ=男，ค่ะ/คะ=女。"""
    lang_name = {"th": "Thai", "en": "English"}.get(language, "Thai")
    prompt = (
        f"Analyze this {lang_name} text for a language-learning audio lesson.\n"
        "1. Split it into natural sentences (each item should be one spoken sentence, "
        "not too long; split long sentences at natural pauses).\n"
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
        "Return ONLY a JSON array: "
        '[{"text": "...", "speaker": "A", "gender": "female", "emotion": "..."}]\n\n'
        + text
    )
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    resp = requests.post(
        GEMINI_URL.format(model=model, key=_gemini_key()),
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0},
        },
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini 分句失败 {resp.status_code}: {resp.text[:200]}")
    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
    items = json.loads(raw)
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
    return script


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
    """Gemini TTS 生成单句，带情感指令"""
    model = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
    voice = GEMINI_VOICES.get(voice_slot, "Kore")
    styled = f"Say in a {emotion} tone: {text}" if emotion else text
    resp = requests.post(
        GEMINI_URL.format(model=model, key=_gemini_key()),
        json={
            "contents": [{"parts": [{"text": styled}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
                },
            },
        },
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini TTS 失败 {resp.status_code}: {resp.text[:200]}")
    data = resp.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
    pcm = base64.b64decode(data)
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


# ========== 封面插画（Gemini 图片生成） ==========

def generate_cover_image(text, language, out_path):
    """根据文本内容生成一张卡通风格封面插画。失败时返回 False，不影响主流程。"""
    model = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
    lang_name = {"th": "Thai", "en": "English"}.get(language, "")
    prompt = (
        "Create ONE simple, warm, flat-design cartoon illustration that captures "
        f"the scene or theme of this {lang_name} text. "
        "Style: minimalist flat cartoon, soft colors, cozy mood. "
        "Absolutely NO words, NO letters, NO text in the image.\n\n"
        + text[:400]
    )
    try:
        resp = requests.post(
            GEMINI_URL.format(model=model, key=_gemini_key()),
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
            },
            timeout=90,
        )
        if resp.status_code != 200:
            print(f"[Cover] Gemini 图片生成 {resp.status_code}: {resp.text[:150]}")
            return False
        for part in resp.json()["candidates"][0]["content"]["parts"]:
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
    返回 (audio_filename, segments, script)"""
    def report(msg):
        if progress:
            progress(msg)

    report("正在分析文本、分配角色...")
    script = prepare_script(text, language)

    tmpdir = tempfile.mkdtemp(prefix="tts_")
    clips = []
    try:
        for i, item in enumerate(script):
            report(f"正在生成语音 {i + 1}/{len(script)}...")
            slot = _voice_slot(item["speaker"], item["gender"])
            clip = os.path.join(tmpdir, f"clip_{i:03d}.wav")
            if engine == "azure":
                azure_tts_sentence(item["text"], slot, language, clip)
            else:
                gemini_tts_sentence(item["text"], slot, item["emotion"], clip)
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

        return audio_name, segments, script
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
