import os
import subprocess
import threading
from openai import OpenAI


def transcribe_video(video_path, provider="groq"):
    """
    对视频进行语音识别和断句。
    provider: "groq" | "azure" | "combined"
    """
    if provider == "azure":
        result = transcribe_azure(video_path)
    elif provider == "combined":
        result = transcribe_combined(video_path)
    else:
        result = transcribe_groq(video_path)

    result["segments"] = fix_timestamps(result["segments"])
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
            languages=["th-TH", "en-US"]
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

        lang_map = {"th-TH": "th", "en-US": "en"}
        language = lang_map.get(detected_lang, detected_lang)

        return {
            "segments": segments,
            "language": language,
        }

    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)


def get_azure_full_text(video_path):
    """调用 Azure Speech 获取完整识别文本（拼接所有片段）"""
    result = transcribe_azure(video_path)
    full_text = "".join(seg["text"] for seg in result["segments"])
    return full_text, result.get("language", "unknown")


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


def transcribe_combined(video_path):
    """
    智能校准模式：Groq 断句 + Azure 文本校准。
    1. Groq Whisper 识别 → 带时间戳的断句
    2. Azure Speech 识别 → 准确的完整文本
    3. LCS 对齐 → 用 Azure 文本替换 Groq 每句的文字
    """
    # 并行调用 Groq 和 Azure
    groq_result = [None]
    azure_text = [None]
    azure_lang = [None]
    errors = []

    def run_groq():
        try:
            groq_result[0] = transcribe_groq(video_path)
        except Exception as e:
            errors.append(f"Groq 识别失败: {e}")

    def run_azure():
        try:
            text, lang = get_azure_full_text(video_path)
            azure_text[0] = text
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

    # 如果 Azure 也成功了，执行校准
    if azure_text[0]:
        result["segments"] = align_and_calibrate(
            result["segments"], azure_text[0]
        )
        # 优先使用 Azure 检测的语言
        if azure_lang[0] and azure_lang[0] != "unknown":
            result["language"] = azure_lang[0]

    return result
