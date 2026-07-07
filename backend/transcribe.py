import os
import subprocess
import threading
from openai import OpenAI


def transcribe_video(video_path, provider="groq", segment_target=None):
    """
    对视频进行语音识别和断句。
    provider: "groq" | "azure" | "combined"
    segment_target: 目标句子长度（字符数），None 表示不调整
    """
    if provider == "azure":
        result = transcribe_azure(video_path)
    elif provider == "combined":
        result = transcribe_combined(video_path)
    else:
        result = transcribe_groq(video_path)

    result["segments"] = fix_timestamps(result["segments"])

    if segment_target:
        result["segments"] = normalize_segments(result["segments"], segment_target)

    return result


def fix_timestamps(segments):
    """
    修复时间戳异常：
    1. end <= start → 根据文本长度估算合理的 end
    2. 时长太短（文字多但时间极短）→ 扩展 end
    3. 与下一句重叠 → 截断到下一句的 start
    4. 重新编号
    """
    if not segments:
        return segments

    fixed = []
    for seg in segments:
        seg = dict(seg)
        start = seg["start"]
        end = seg["end"]
        text_len = len(seg.get("text", ""))

        # 根据文本长度估算最短时长（泰语大约每秒 5-8 个字符）
        min_duration = max(1.0, text_len / 6.0)

        if end <= start:
            # 结束时间在开始时间之前，用估算时长修复
            seg["end"] = round(start + min_duration, 2)
        elif (end - start) < min_duration * 0.3:
            # 时长过短（不到估算值的 30%），扩展
            seg["end"] = round(start + min_duration, 2)

        fixed.append(seg)

    # 确保不与下一句重叠
    for i in range(len(fixed) - 1):
        if fixed[i]["end"] > fixed[i + 1]["start"]:
            fixed[i]["end"] = fixed[i + 1]["start"]

    # 确保时间顺序：按 start 排序，重新编号
    fixed.sort(key=lambda s: s["start"])
    for i, seg in enumerate(fixed):
        seg["index"] = i

    return fixed


def normalize_segments(segments, target_len):
    """
    归一化句子长度：合并过短的句子，拆分过长的句子。
    target_len: 目标字符数（如 15=短句, 30=中等, 50=长句）
    """
    if not segments or target_len <= 0:
        return segments

    min_len = max(5, target_len // 3)
    max_len = target_len * 2

    # 第一步：合并过短的句子
    merged = []
    for seg in segments:
        if merged and len(merged[-1]["text"]) < min_len:
            # 当前句太短，与下一句合并
            prev = merged[-1]
            prev["text"] = prev["text"] + " " + seg["text"]
            prev["end"] = seg["end"]
        elif merged and len(seg["text"]) < min_len:
            # 下一句太短，合并到前一句
            prev = merged[-1]
            prev["text"] = prev["text"] + " " + seg["text"]
            prev["end"] = seg["end"]
        else:
            merged.append(dict(seg))

    # 第二步：拆分过长的句子
    result = []
    for seg in merged:
        text = seg["text"]
        if len(text) <= max_len:
            result.append(seg)
            continue

        # 按空格或泰语常见断点拆分
        duration = seg["end"] - seg["start"]
        chars_per_sec = len(text) / duration if duration > 0 else 10

        chunks = _split_text(text, target_len)
        chunk_start = seg["start"]
        for chunk in chunks:
            chunk_dur = len(chunk) / chars_per_sec
            result.append({
                "text": chunk,
                "start": round(chunk_start, 2),
                "end": round(chunk_start + chunk_dur, 2),
            })
            chunk_start += chunk_dur

    # 重新编号
    for i, seg in enumerate(result):
        seg["index"] = i

    return result


def _split_text(text, target_len):
    """将长文本按目标长度拆分，尽量在空格处断开"""
    chunks = []
    while len(text) > target_len * 1.5:
        # 在 target_len 附近找空格
        split_pos = target_len
        # 向后找空格
        space_after = text.find(" ", target_len)
        # 向前找空格
        space_before = text.rfind(" ", 0, target_len)

        if space_after != -1 and space_after < target_len * 1.5:
            split_pos = space_after + 1
        elif space_before > target_len * 0.5:
            split_pos = space_before + 1
        else:
            split_pos = target_len

        chunks.append(text[:split_pos].strip())
        text = text[split_pos:].strip()

    if text:
        chunks.append(text)

    return chunks


# ========== Groq Whisper ==========

def transcribe_groq(video_path):
    client = OpenAI(
        api_key=os.getenv("GROQ_API_KEY"),
        base_url="https://api.groq.com/openai/v1",
    )
    if not os.getenv("GROQ_API_KEY"):
        raise ValueError("未配置 GROQ_API_KEY")

    with open(video_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    segments = []
    for i, seg in enumerate(result.segments):
        segments.append({
            "index": i,
            "text": (seg.text if hasattr(seg, "text") else seg["text"]).strip(),
            "start": round(seg.start if hasattr(seg, "start") else seg["start"], 2),
            "end": round(seg.end if hasattr(seg, "end") else seg["end"], 2),
        })

    return {
        "segments": segments,
        "language": getattr(result, "language", "unknown"),
    }


# ========== Azure Speech ==========

def extract_audio_wav(video_path):
    """从视频提取 WAV 音频（16kHz 单声道），供 Azure 使用"""
    wav_path = video_path + ".tmp_transcribe.wav"
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-ar", "16000",
        "-ac", "1",
        "-sample_fmt", "s16",
        wav_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"音频提取失败: {result.stderr[-300:]}")
    return wav_path


def transcribe_azure(video_path):
    import azure.cognitiveservices.speech as speechsdk

    speech_key = os.environ.get("AZURE_SPEECH_KEY", "")
    speech_region = os.environ.get("AZURE_SPEECH_REGION", "")
    if not speech_key or not speech_region:
        raise RuntimeError("请在 .env 中配置 AZURE_SPEECH_KEY 和 AZURE_SPEECH_REGION")

    wav_path = extract_audio_wav(video_path)

    try:
        speech_config = speechsdk.SpeechConfig(
            subscription=speech_key, region=speech_region
        )
        auto_detect_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=["th-TH", "en-US", "ja-JP", "ko-KR", "fr-FR", "de-DE", "es-ES", "pt-BR", "ru-RU", "it-IT"]
        )
        audio_config = speechsdk.audio.AudioConfig(filename=wav_path)

        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
            auto_detect_source_language_config=auto_detect_config,
        )

        segments = []
        done_event = threading.Event()
        detected_lang = "unknown"

        def on_recognized(evt):
            nonlocal detected_lang
            if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
                text = evt.result.text.strip()
                if not text:
                    return
                offset_s = evt.result.offset / 10_000_000
                duration_s = evt.result.duration / 10_000_000
                segments.append({
                    "text": text,
                    "start": round(offset_s, 2),
                    "end": round(offset_s + duration_s, 2),
                })
                lang_result = speechsdk.AutoDetectSourceLanguageResult(evt.result)
                lang = lang_result.language
                if lang and lang != "Unknown":
                    detected_lang = lang

        def on_session_stopped(evt):
            done_event.set()

        def on_canceled(evt):
            if evt.cancellation_details.reason == speechsdk.CancellationReason.Error:
                print(f"Azure Speech 错误: {evt.cancellation_details.error_details}")
            done_event.set()

        recognizer.recognized.connect(on_recognized)
        recognizer.session_stopped.connect(on_session_stopped)
        recognizer.canceled.connect(on_canceled)

        recognizer.start_continuous_recognition()
        done_event.wait(timeout=300)
        recognizer.stop_continuous_recognition()

        for i, seg in enumerate(segments):
            seg["index"] = i

        lang_map = {
            "th-TH": "th", "en-US": "en", "ja-JP": "ja", "ko-KR": "ko",
            "fr-FR": "fr", "de-DE": "de", "es-ES": "es", "pt-BR": "pt",
            "ru-RU": "ru", "it-IT": "it",
        }
        language = lang_map.get(detected_lang, detected_lang)

        return {
            "segments": segments,
            "language": language,
        }

    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)


def transcribe_slice(audio_path, provider="groq", language=None):
    """识别一个音频切片（已切好的短音频文件），返回拼接后的完整文本。
    language: 短语言码如 "th"/"en"，Azure 需要明确语言（自动检测限 4 种会报错）"""
    if provider == "azure":
        result = transcribe_azure_slice(audio_path, language)
    elif provider == "gemini":
        result = transcribe_gemini_slice(audio_path, language)
    else:
        result = transcribe_groq(audio_path)
    text = " ".join(seg["text"] for seg in result["segments"]).strip()
    return {"text": text, "language": result.get("language", "unknown")}


LANG_NAME_MAP = {
    "th": "Thai", "en": "English", "ja": "Japanese", "ko": "Korean",
    "fr": "French", "de": "German", "es": "Spanish", "pt": "Portuguese",
    "ru": "Russian", "it": "Italian", "zh": "Chinese", "vi": "Vietnamese", "hi": "Hindi",
}


def transcribe_gemini_slice(wav_path, language=None):
    """用 Google Gemini 识别短音频切片（REST API，只需 GEMINI_API_KEY）"""
    import base64
    import requests

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("请在 .env 中配置 GEMINI_API_KEY（在 aistudio.google.com 免费申请）")

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    short = (language or "")[:2].lower()
    lang_name = LANG_NAME_MAP.get(short, "")
    lang_hint = f"The audio is in {lang_name}. " if lang_name else ""

    with open(wav_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode()

    from tts import _gemini_request
    payload = {
        "contents": [{
            "parts": [
                {"text": (
                    f"{lang_hint}Transcribe this audio verbatim. "
                    "Output ONLY the exact transcription text, nothing else. "
                    "No explanations, no labels, no punctuation additions beyond what is spoken."
                )},
                {"inline_data": {"mime_type": "audio/wav", "data": audio_b64}},
            ]
        }],
        "generationConfig": {"temperature": 0},
    }

    data = _gemini_request(model, payload, timeout=60, tag="Gemini识别")
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        raise RuntimeError(f"Gemini 返回格式异常: {str(data)[:200]}")

    return {
        "segments": [{"index": 0, "text": text, "start": 0, "end": 0}] if text else [],
        "language": short or "unknown",
    }


def add_word_spacing(texts, language="th"):
    """用 Gemini 给无空格语言（如泰语）的文本按词加空格，方便学习者阅读。
    只插入空格，不改动任何字符；失败时原样返回。"""
    import json as _json
    import requests

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key or not texts:
        return texts

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    lang_name = {"th": "Thai", "ja": "Japanese", "km": "Khmer", "lo": "Lao", "my": "Burmese"}.get(
        (language or "")[:2].lower(), "Thai")

    numbered = "\n".join(f"{i}\t{t}" for i, t in enumerate(texts))
    prompt = (
        f"The following numbered lines are {lang_name} sentences (index TAB text).\n"
        f"Task: insert a single space between every {lang_name} word "
        "(word segmentation to help language learners read).\n"
        "Rules: do NOT change, add, remove, or reorder any characters — "
        "only insert spaces. Keep existing spaces/punctuation as-is.\n"
        "Return ONLY a JSON array of strings in the same order, no explanations, no markdown.\n\n"
        + numbered
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0},
    }
    try:
        from tts import _gemini_request
        resp_json = _gemini_request(model, payload, timeout=60, max_retries=3, tag="分词")
        raw = resp_json["candidates"][0]["content"]["parts"][0]["text"].strip()
        # 去掉可能的 markdown 代码块包裹
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        spaced = _json.loads(raw)
        if not isinstance(spaced, list) or len(spaced) != len(texts):
            print("[WordSpacing] 返回数量不匹配，放弃")
            return texts
        # 安全校验：除空格外内容必须完全一致，否则该句保留原文
        result = []
        for orig, sp in zip(texts, spaced):
            if isinstance(sp, str) and sp.replace(" ", "") == orig.replace(" ", ""):
                result.append(sp.strip())
            else:
                result.append(orig)
        return result
    except Exception as e:
        print(f"[WordSpacing] 失败: {e}")
        return texts


AZURE_LOCALE_MAP = {
    "th": "th-TH", "en": "en-US", "ja": "ja-JP", "ko": "ko-KR",
    "fr": "fr-FR", "de": "de-DE", "es": "es-ES", "pt": "pt-BR",
    "ru": "ru-RU", "it": "it-IT", "zh": "zh-CN", "vi": "vi-VN", "hi": "hi-IN",
}


def transcribe_azure_slice(wav_path, language=None):
    """用 Azure 识别短音频切片，明确指定语言（不用自动检测）"""
    import azure.cognitiveservices.speech as speechsdk

    speech_key = os.environ.get("AZURE_SPEECH_KEY", "")
    speech_region = os.environ.get("AZURE_SPEECH_REGION", "")
    if not speech_key or not speech_region:
        raise RuntimeError("请在 .env 中配置 AZURE_SPEECH_KEY 和 AZURE_SPEECH_REGION")

    short = (language or "en")[:2].lower()
    locale = AZURE_LOCALE_MAP.get(short, "en-US")

    speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
    speech_config.speech_recognition_language = locale
    audio_config = speechsdk.audio.AudioConfig(filename=wav_path)
    recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config, audio_config=audio_config
    )

    segments = []
    done_event = threading.Event()

    def on_recognized(evt):
        import azure.cognitiveservices.speech as sdk
        if evt.result.reason == sdk.ResultReason.RecognizedSpeech:
            text = evt.result.text.strip()
            if text:
                offset_s = evt.result.offset / 10_000_000
                duration_s = evt.result.duration / 10_000_000
                segments.append({
                    "text": text,
                    "start": round(offset_s, 2),
                    "end": round(offset_s + duration_s, 2),
                })

    def on_stopped(evt):
        done_event.set()

    def on_canceled(evt):
        if evt.cancellation_details.reason == speechsdk.CancellationReason.Error:
            print(f"Azure Slice 错误: {evt.cancellation_details.error_details}")
        done_event.set()

    recognizer.recognized.connect(on_recognized)
    recognizer.session_stopped.connect(on_stopped)
    recognizer.canceled.connect(on_canceled)

    recognizer.start_continuous_recognition()
    done_event.wait(timeout=120)
    recognizer.stop_continuous_recognition()

    for i, seg in enumerate(segments):
        seg["index"] = i

    return {"segments": segments, "language": short}


def get_azure_result(video_path):
    """调用 Azure Speech，返回完整的 segments 列表和语言"""
    result = transcribe_azure(video_path)
    return result["segments"], result.get("language", "unknown")


# ========== 智能校准：Groq 断句 + Azure 文本 ==========

def lcs_alignment(src, tgt):
    """
    用 LCS（最长公共子序列）对齐两段文本。
    返回列表：[(src_idx, tgt_idx), ...] 表示匹配的字符位置对。
    """
    m, n = len(src), len(tgt)

    # 空间优化：只需要两行来计算 LCS 长度，但回溯需要完整矩阵
    # 对于短视频字幕（通常 < 2000 字符），完整矩阵可以接受
    if m * n > 5_000_000:
        # 文本太长，用分治 Hirschberg 的简化版：按段落粗对齐
        return _approx_alignment(src, tgt)

    # 标准 LCS DP
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if src[i - 1] == tgt[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    # 回溯找匹配对
    pairs = []
    i, j = m, n
    while i > 0 and j > 0:
        if src[i - 1] == tgt[j - 1]:
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            i -= 1
        else:
            j -= 1

    pairs.reverse()
    return pairs


def _approx_alignment(src, tgt):
    """
    当文本太长时用近似对齐：
    将 src 按固定长度分块，在 tgt 中顺序查找每块的最佳匹配位置。
    """
    chunk_size = 50
    pairs = []
    tgt_pos = 0

    for start in range(0, len(src), chunk_size):
        chunk = src[start:start + chunk_size]
        # 在 tgt[tgt_pos:] 中找最佳匹配
        best_pos = -1
        best_score = -1
        search_end = min(tgt_pos + len(chunk) * 3, len(tgt))

        for p in range(tgt_pos, max(tgt_pos, search_end - len(chunk) + 1)):
            score = sum(1 for a, b in zip(chunk, tgt[p:p + len(chunk)]) if a == b)
            if score > best_score:
                best_score = score
                best_pos = p

        if best_pos >= 0 and best_score > len(chunk) * 0.3:
            for k, ch in enumerate(chunk):
                if best_pos + k < len(tgt) and ch == tgt[best_pos + k]:
                    pairs.append((start + k, best_pos + k))
            tgt_pos = best_pos + len(chunk)

    return pairs


def align_and_calibrate(groq_segments, azure_full_text):
    """
    用 Azure 的完整文本校准 Groq 的逐句文本。
    保留 Groq 的时间戳和断句结构，用 Azure 的文字替换。

    算法：
    1. 拼接 Groq 全部句子文本
    2. 用 LCS 对齐 Groq 全文 ↔ Azure 全文，建立字符映射
    3. 根据每句在 Groq 全文中的起止位置，找到对应的 Azure 文本区间
    4. 用 Azure 区间的文本替换该句内容
    """
    # 拼接 Groq 全文，记录每句的字符起止位置
    groq_full = ""
    seg_ranges = []  # [(start_in_full, end_in_full), ...]
    for seg in groq_segments:
        start = len(groq_full)
        groq_full += seg["text"]
        end = len(groq_full)
        seg_ranges.append((start, end))

    if not groq_full or not azure_full_text:
        return groq_segments

    # LCS 对齐
    pairs = lcs_alignment(groq_full, azure_full_text)

    if not pairs:
        return groq_segments

    # 建立 groq_idx → azure_idx 的映射
    groq_to_azure = {}
    for g_idx, a_idx in pairs:
        groq_to_azure[g_idx] = a_idx

    # 对每句，找到对应的 Azure 文本区间的起点
    seg_azure_starts = []
    for i, seg in enumerate(groq_segments):
        seg_start, seg_end = seg_ranges[i]
        first_azure = None
        for g_idx in range(seg_start, seg_end):
            if g_idx in groq_to_azure:
                first_azure = groq_to_azure[g_idx]
                break
        seg_azure_starts.append(first_azure)

    # 用下一句的起点作为当前句的终点，最后一句延伸到 Azure 全文末尾
    calibrated = []
    for i, seg in enumerate(groq_segments):
        a_start = seg_azure_starts[i]
        if a_start is None:
            calibrated.append(seg)
            continue

        # 找下一句的 Azure 起点作为当前句的终点
        a_end = len(azure_full_text)
        for j in range(i + 1, len(groq_segments)):
            if seg_azure_starts[j] is not None:
                a_end = seg_azure_starts[j]
                break

        azure_slice = azure_full_text[a_start:a_end].strip()
        if azure_slice:
            seg = dict(seg)
            seg["text"] = azure_slice
        calibrated.append(seg)

    return calibrated


def fill_gaps_with_azure(groq_segments, azure_segments, gap_threshold=1.0):
    """
    检测 Groq 句子之间的大间隔，用 Azure 的识别结果填充被遗漏的语音。
    gap_threshold: 间隔超过这个秒数就尝试填补
    """
    if not azure_segments or not groq_segments:
        return groq_segments

    merged = list(groq_segments)
    inserts = []

    for i in range(len(merged) - 1):
        gap_start = merged[i]["end"]
        gap_end = merged[i + 1]["start"]
        gap = gap_end - gap_start

        if gap < gap_threshold:
            continue

        # 在这个间隔里找 Azure 识别到的句子
        for az_seg in azure_segments:
            # Azure 句子的主体落在间隔内
            az_mid = (az_seg["start"] + az_seg["end"]) / 2
            if gap_start - 0.5 <= az_mid <= gap_end + 0.5:
                inserts.append({
                    "text": az_seg["text"],
                    "start": max(az_seg["start"], gap_start),
                    "end": min(az_seg["end"], gap_end),
                })

    if inserts:
        merged.extend(inserts)
        merged.sort(key=lambda s: s["start"])
        for i, seg in enumerate(merged):
            seg["index"] = i

    return merged


def transcribe_combined(video_path):
    """
    智能校准模式：Groq 断句 + Azure 文本校准 + 间隔填补。
    1. Groq Whisper 识别 → 带时间戳的断句
    2. Azure Speech 识别 → 准确的文本 + 带时间戳的片段
    3. LCS 对齐 → 用 Azure 文本替换 Groq 每句的文字
    4. 间隔填补 → 检测 Groq 句子间的大间隔，用 Azure 片段填充
    """
    # 并行调用 Groq 和 Azure
    groq_result = [None]
    azure_segments = [None]
    azure_lang = [None]
    errors = []

    def run_groq():
        try:
            groq_result[0] = transcribe_groq(video_path)
        except Exception as e:
            errors.append(f"Groq 识别失败: {e}")

    def run_azure():
        try:
            segs, lang = get_azure_result(video_path)
            azure_segments[0] = segs
            azure_lang[0] = lang
        except Exception as e:
            errors.append(f"Azure 识别失败: {e}")

    t1 = threading.Thread(target=run_groq)
    t2 = threading.Thread(target=run_azure)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    if groq_result[0] is None:
        raise RuntimeError("; ".join(errors) or "Groq 识别失败")

    result = groq_result[0]

    # 如果 Azure 也成功了，执行校准 + 间隔填补
    if azure_segments[0]:
        azure_full_text = "".join(seg["text"] for seg in azure_segments[0])

        # 文本校准
        result["segments"] = align_and_calibrate(
            result["segments"], azure_full_text
        )

        # 间隔填补
        result["segments"] = fill_gaps_with_azure(
            result["segments"], azure_segments[0]
        )

        # 优先使用 Azure 检测的语言
        if azure_lang[0] and azure_lang[0] != "unknown":
            result["language"] = azure_lang[0]

    return result
