"""
语音识别服务层
业务模块通过此模块访问全部 ASR 能力，不知道底层是 Groq / OpenAI / Azure / Gemini。
保持与原 transcribe.py 完全相同的公开函数签名和返回格式。
"""
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading

from config import providers, settings, get_logger
from ai.provider import groq as groq_provider
from ai.provider import openai_whisper as openai_provider
from ai.provider import azure as azure_provider
from ai.provider import gemini as gemini_provider
from ai.provider import qwen_asr as qwen_provider

logger = get_logger(__name__)

# 超过此时长（秒）自动分段识别；每段时长
_CHUNK_THRESHOLD = 300   # 5 分钟以上才切段
_CHUNK_SIZE      = 180   # 每段 3 分钟
# OpenAI transcription 的保守音频大小上限（留一点余量，避免贴边踩 25MB 限制）
_OPENAI_MAX_AUDIO_BYTES = 24 * 1024 * 1024

# OpenAI Whisper-1 返回英文全名（"chinese"），Groq 返回 ISO 码（"zh"）
# 所有读取 result_obj.language 的地方必须经过此表归一化
_LANG_NAME_TO_ISO = {
    "chinese": "zh", "english": "en", "japanese": "ja", "korean": "ko",
    "thai": "th", "french": "fr", "german": "de", "spanish": "es",
    "portuguese": "pt", "russian": "ru", "italian": "it", "vietnamese": "vi",
    "hindi": "hi", "arabic": "ar", "dutch": "nl", "polish": "pl",
    "turkish": "tr", "indonesian": "id", "malay": "ms", "swedish": "sv",
    "danish": "da", "norwegian": "no", "finnish": "fi", "czech": "cs",
    "romanian": "ro", "hungarian": "hu", "greek": "el", "hebrew": "he",
    "ukrainian": "uk", "catalan": "ca", "croatian": "hr",
}


# ── 工具函数 ────────────────────────────────────────────────────────────────────

def _safe_wav_path(video_path, suffix):
    h = hashlib.md5(video_path.encode()).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), f"{h}_{suffix}.wav")


def get_video_duration(video_path):
    """用 ffprobe 获取视频时长（秒），失败返回 0"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path],
            capture_output=True, text=True, timeout=settings.TIMEOUT_FFPROBE,
        )
        if r.returncode == 0:
            return float(json.loads(r.stdout).get("format", {}).get("duration", 0))
    except Exception:
        pass
    return 0


def _extract_chunk_wav(video_path, start, duration):
    wav_path = _safe_wav_path(video_path, f"chunk_{int(start)}")
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start), "-i", video_path,
        "-t", str(duration),
        "-map", "0:a",
        "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
        wav_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        err = r.stderr
        if "matches no streams" in err or "does not contain any stream" in err or "Invalid argument" in err:
            raise RuntimeError("视频没有音频轨道，无法识别。请检查下载的视频文件是否包含音频。")
        raise RuntimeError(f"分段提取失败: {err[-300:]}")
    return wav_path


def _format_openai_too_large_error(wav_path, prefix="音频文件过大"):
    size_mb = os.path.getsize(wav_path) / (1024 * 1024)
    return (
        f"{prefix}（约 {size_mb:.1f}MB，超过 OpenAI 单次上传限制）。"
        "请缩短片段、改用 Groq/Azure，或把视频切得更短后再试。"
    )


def _is_openai_too_large_error(exc) -> bool:
    msg = str(exc).lower()
    status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    return bool(
        status_code == 413
        or "request_too_large" in msg
        or "request entity too large" in msg
        or "payload too large" in msg
        or "超过 openai 单次上传限制" in msg
        or "识别请求过大" in msg
    )


def _transcribe_openai_wav(wav_path):
    """调用 OpenAI 转写前先做大小检查，并把 413 包装成可执行提示。"""
    size = os.path.getsize(wav_path)
    if size > _OPENAI_MAX_AUDIO_BYTES:
        raise RuntimeError(_format_openai_too_large_error(wav_path))

    try:
        return openai_provider.transcribe_file(
            wav_path, timestamp_granularities=["segment", "word"]
        )
    except Exception as exc:
        msg = str(exc)
        lower = msg.lower()
        status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        if (
            status_code == 413
            or "request_too_large" in lower
            or "request entity too large" in lower
            or "payload too large" in lower
        ):
            raise RuntimeError(_format_openai_too_large_error(wav_path, "识别请求过大")) from exc
        raise


def _transcribe_groq_wav(wav_path):
    result_obj = groq_provider.transcribe_file(
        wav_path, timestamp_granularities=["segment", "word"]
    )
    segments, words, language = _parse_result_obj(result_obj)
    out = {"segments": segments, "language": language}
    if words:
        out["words"] = words
    return out


def _apply_offset(segs_raw, words_raw, offset):
    """把识别结果加上时间偏移，返回 (segments_list, words_list)"""
    segments = []
    for seg in segs_raw:
        text  = (seg.text  if hasattr(seg, "text")  else seg["text"]).strip()
        start = (seg.start if hasattr(seg, "start") else seg["start"])
        end   = (seg.end   if hasattr(seg, "end")   else seg["end"])
        if not text:
            continue
        s = {
            "text":  text,
            "start": round(start + offset, 2),
            "end":   round(end   + offset, 2),
        }
        seg_dict  = seg if isinstance(seg, dict) else (vars(seg) if hasattr(seg, "__dict__") else {})
        logprob   = seg_dict.get("avg_logprob")
        no_speech = seg_dict.get("no_speech_prob")
        if logprob   is not None: s["_logprob"]   = round(float(logprob),   4)
        if no_speech is not None: s["_no_speech"] = round(float(no_speech), 4)
        segments.append(s)
    words = []
    for w in words_raw:
        wt = (w.word  if hasattr(w, "word")  else w.get("word", "")).strip()
        ws = (w.start if hasattr(w, "start") else w.get("start", 0))
        we = (w.end   if hasattr(w, "end")   else w.get("end",   0))
        words.append({"word": wt, "start": round(ws + offset, 3), "end": round(we + offset, 3)})
    return segments, words


def _parse_result_obj(result_obj, index_start=0):
    """将 OpenAI SDK Transcription 对象解析为 (segments, words, language) 三元组"""
    segments = []
    for i, seg in enumerate(result_obj.segments or []):
        s = {
            "index": index_start + i,
            "text":  (seg.text if hasattr(seg, "text") else seg["text"]).strip(),
            "start": round(seg.start if hasattr(seg, "start") else seg["start"], 2),
            "end":   round(seg.end   if hasattr(seg, "end")   else seg["end"],   2),
        }
        seg_dict  = seg if isinstance(seg, dict) else (vars(seg) if hasattr(seg, "__dict__") else {})
        logprob   = seg_dict.get("avg_logprob")
        no_speech = seg_dict.get("no_speech_prob")
        if i == 0:
            logger.debug(f"segment fields: {list(seg_dict.keys())}")
        if logprob   is not None: s["_logprob"]   = round(float(logprob),   4)
        if no_speech is not None: s["_no_speech"] = round(float(no_speech), 4)
        segments.append(s)

    words = []
    if hasattr(result_obj, "words") and result_obj.words:
        for w in result_obj.words:
            wt = (w.word  if hasattr(w, "word")  else w.get("word",  ""))
            ws = (w.start if hasattr(w, "start") else w.get("start", 0))
            we = (w.end   if hasattr(w, "end")   else w.get("end",   0))
            words.append({"word": wt.strip(), "start": round(ws, 3), "end": round(we, 3)})

    language = getattr(result_obj, "language", "unknown") or "unknown"
    language = _LANG_NAME_TO_ISO.get(language.lower(), language)
    return segments, words, language


# ── Groq ────────────────────────────────────────────────────────────────────────

def transcribe_groq(video_path):
    result_obj = groq_provider.transcribe_file(
        video_path, timestamp_granularities=["segment", "word"]
    )
    segments, words, language = _parse_result_obj(result_obj)
    out = {"segments": segments, "language": language}
    if words:
        out["words"] = words
    return out


# ── OpenAI ──────────────────────────────────────────────────────────────────────

def transcribe_openai(video_path):
    """使用 OpenAI whisper-1。提取 WAV 音频（<25MB）避免超限。"""
    wav_path = _safe_wav_path(video_path, "openai")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-map", "0:a", "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
        wav_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        err = r.stderr
        if "matches no streams" in err or "does not contain any stream" in err or "Invalid argument" in err:
            raise RuntimeError("视频没有音频轨道，无法识别。请检查下载的视频文件是否包含音频。")
        raise RuntimeError(f"音频提取失败: {err[-300:]}")
    try:
        result_obj = _transcribe_openai_wav(wav_path)
        segments, words, language = _parse_result_obj(result_obj)
        out = {"segments": segments, "language": language}
        if words:
            out["words"] = words
        return out
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)


# ── Azure ────────────────────────────────────────────────────────────────────────

def extract_audio_wav(video_path):
    """从视频提取 WAV 音频（16kHz 单声道），供 Azure 使用"""
    wav_path = _safe_wav_path(video_path, "azure")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-map", "0:a", "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
        wav_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err = result.stderr
        if "matches no streams" in err or "does not contain any stream" in err or "Invalid argument" in err:
            raise RuntimeError("视频没有音频轨道，无法识别。请检查下载的视频文件是否包含音频。")
        raise RuntimeError(f"音频提取失败: {err[-300:]}")
    return wav_path


def transcribe_azure(video_path):
    wav_path = extract_audio_wav(video_path)
    try:
        return azure_provider.transcribe_full(wav_path)
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)


def transcribe_azure_slice(wav_path, language=None):
    return azure_provider.transcribe_slice(wav_path, language)


# ── Qwen3-ASR ────────────────────────────────────────────────────────────────────

def transcribe_qwen(video_path):
    """
    使用 Qwen3-ASR（DashScope）转写视频。
    流程：提取 WAV → 上传 DashScope → 异步转写 → 轮询 → 解析词级时间戳。
    """
    wav_path = _safe_wav_path(video_path, "qwen")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-map", "0:a", "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
        wav_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        err = r.stderr
        if "matches no streams" in err or "does not contain any stream" in err or "Invalid argument" in err:
            raise RuntimeError("视频没有音频轨道，无法识别。请检查下载的视频文件是否包含音频。")
        raise RuntimeError(f"音频提取失败: {err[-300:]}")
    try:
        result = qwen_provider.transcribe_file(wav_path)
        # result 已是内部格式：{"segments": [...], "language": str, "words": [...]}
        # 语言码用 _LANG_NAME_TO_ISO 再过一次归一化（Qwen 可能返回全名）
        lang = result.get("language", "unknown")
        result["language"] = _LANG_NAME_TO_ISO.get(lang.lower(), lang)
        return result
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)


def get_azure_result(video_path):
    result = transcribe_azure(video_path)
    return result["segments"], result.get("language", "unknown")


# ── Gemini slice ────────────────────────────────────────────────────────────────

LANG_NAME_MAP = {
    "th": "Thai", "en": "English", "ja": "Japanese", "ko": "Korean",
    "fr": "French", "de": "German", "es": "Spanish", "pt": "Portuguese",
    "ru": "Russian", "it": "Italian", "zh": "Chinese", "vi": "Vietnamese", "hi": "Hindi",
}


def transcribe_gemini_slice(wav_path, language=None):
    """用 Gemini 识别短音频切片（REST API）"""
    import base64

    api_key = providers.Gemini.API_KEY
    if not api_key:
        raise RuntimeError("请在 .env 中配置 GEMINI_API_KEY（在 aistudio.google.com 免费申请）")

    model     = providers.Gemini.TEXT_MODEL
    short     = (language or "")[:2].lower()
    lang_name = LANG_NAME_MAP.get(short, "")
    lang_hint = f"The audio is in {lang_name}. " if lang_name else ""

    with open(wav_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode()

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
    data = gemini_provider.request(
        model, payload, timeout=settings.TIMEOUT_GEMINI_DEFAULT, tag="Gemini识别"
    )
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        raise RuntimeError(f"Gemini 返回格式异常: {str(data)[:200]}")

    return {
        "segments": [{"index": 0, "text": text, "start": 0, "end": 0}] if text else [],
        "language": short or "unknown",
    }


# ── 分段识别（长视频）──────────────────────────────────────────────────────────

def transcribe_chunked(video_path, provider, duration, progress_callback=None):
    """将长视频分成 _CHUNK_SIZE 秒一段，逐段识别后合并。"""
    chunk_starts = list(range(0, int(duration), _CHUNK_SIZE))
    total        = len(chunk_starts)
    all_segments = []
    all_words    = []
    language     = "unknown"

    for idx, start in enumerate(chunk_starts):
        chunk_dur = min(_CHUNK_SIZE, duration - start)
        if progress_callback:
            m, s = divmod(int(start), 60)
            progress_callback(f"正在识别第 {idx+1}/{total} 段（{m}:{s:02d} 起）...")

        wav_path = _extract_chunk_wav(video_path, start, chunk_dur)
        try:
            if provider == "openai":
                result_obj = _transcribe_openai_wav(wav_path)
            else:  # groq
                result_obj = groq_provider.transcribe_file(
                    wav_path, timestamp_granularities=["segment", "word"]
                )
            segs_raw  = result_obj.segments or []
            words_raw = result_obj.words or []
            lang      = _LANG_NAME_TO_ISO.get(
                (getattr(result_obj, "language", None) or "unknown").lower(),
                getattr(result_obj, "language", "unknown") or "unknown",
            )
        finally:
            if os.path.exists(wav_path):
                os.remove(wav_path)

        if lang and lang != "unknown" and language == "unknown":
            language = lang

        segs, words = _apply_offset(segs_raw, words_raw, start)
        all_segments.extend(segs)
        all_words.extend(words)

    out = {"segments": all_segments, "language": language}
    if all_words:
        out["words"] = all_words
    return out


# ── Combined（Groq 断句 + Azure 校准）──────────────────────────────────────────

def transcribe_combined(video_path):
    """智能校准模式：Groq 断句 + Azure 文本校准 + 间隔填补。"""
    groq_result    = [None]
    azure_segments = [None]
    azure_lang     = [None]
    errors         = []

    def run_groq():
        try:
            groq_result[0] = transcribe_groq(video_path)
        except Exception as e:
            errors.append(f"Groq 识别失败: {e}")

    def run_azure():
        try:
            segs, lang = get_azure_result(video_path)
            azure_segments[0] = segs
            azure_lang[0]     = lang
        except Exception as e:
            errors.append(f"Azure 识别失败: {e}")

    t1 = threading.Thread(target=run_groq)
    t2 = threading.Thread(target=run_azure)
    t1.start(); t2.start()
    t1.join();  t2.join()

    if groq_result[0] is None:
        raise RuntimeError("; ".join(errors) or "Groq 识别失败")

    result = groq_result[0]

    if azure_segments[0]:
        azure_full_text = "".join(seg["text"] for seg in azure_segments[0])
        groq_full       = "".join(seg["text"] for seg in result["segments"])
        logger.info(f"[Combined] Groq {len(result['segments'])} segs, "
                    f"Azure {len(azure_segments[0])} segs")
        logger.debug(f"[Combined] Groq text: {groq_full[:100]}")
        logger.debug(f"[Combined] Azure text: {azure_full_text[:100]}")

        result["segments"] = align_and_calibrate(
            result["segments"], azure_full_text, azure_segments[0]
        )
        result["segments"] = fill_gaps_with_azure(
            result["segments"], azure_segments[0]
        )
        if azure_lang[0] and azure_lang[0] != "unknown":
            result["language"] = azure_lang[0]

    return result


# ── 低置信度重识别 ──────────────────────────────────────────────────────────────

_LOGPROB_THRESHOLD   = -0.5
_NO_SPEECH_THRESHOLD =  0.3


def _is_low_confidence(seg):
    lp = seg.get("_logprob")
    ns = seg.get("_no_speech")
    if lp is not None and lp < _LOGPROB_THRESHOLD:
        return True
    if ns is not None and ns > _NO_SPEECH_THRESHOLD:
        return True
    return False


def _retry_low_confidence_with_groq(video_path, segments, language="unknown",
                                    progress_callback=None):
    """对 OpenAI 低置信度的句子，用 Groq 重识别并替换文本。"""
    if not providers.Groq.API_KEY:
        return

    low_conf = [s for s in segments if _is_low_confidence(s)]
    if not low_conf:
        return

    if progress_callback:
        progress_callback(f"发现 {len(low_conf)} 句置信度偏低，用 Groq 补充识别...")

    lang_hint = language if language not in ("unknown", "") else None

    for seg in low_conf:
        start = seg["start"]
        end   = seg["end"]
        dur   = end - start
        if dur < 0.3:
            continue

        pad       = 0.1
        ext_start = max(0, start - pad)
        ext_dur   = dur + 2 * pad
        wav_path  = _safe_wav_path(video_path, f"retry_{int(start*1000)}")
        try:
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(ext_start), "-i", video_path,
                "-t", str(ext_dur),
                "-map", "0:a",
                "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
                wav_path,
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                continue

            new_text = groq_provider.transcribe_text(wav_path, language=lang_hint)
            new_text = (new_text if isinstance(new_text, str) else "").strip()
            if new_text:
                logger.info(f"[Retry] {start:.1f}s: {seg['text']!r} → {new_text!r}")
                seg["text"] = new_text
                seg.pop("_logprob",   None)
                seg.pop("_no_speech", None)
        except Exception as e:
            logger.warning(f"[Retry] 重识别失败 {start:.1f}s: {e}")
        finally:
            if os.path.exists(wav_path):
                os.remove(wav_path)


# ── 主入口 ──────────────────────────────────────────────────────────────────────

def transcribe_video(video_path, provider="groq", segment_target=None, progress_callback=None):
    """对视频进行语音识别和断句。
    provider: "groq" | "azure" | "combined" | "openai" | "qwen"
    """
    duration    = get_video_duration(video_path)
    use_chunked = duration > _CHUNK_THRESHOLD and provider in ("openai", "groq")

    try:
        if use_chunked:
            result = transcribe_chunked(video_path, provider, duration, progress_callback)
        elif provider == "azure":
            result = transcribe_azure(video_path)
        elif provider == "combined":
            result = transcribe_combined(video_path)
        elif provider == "openai":
            result = transcribe_openai(video_path)
        elif provider == "qwen":
            result = transcribe_qwen(video_path)
        else:
            result = transcribe_groq(video_path)
    except Exception as exc:
        if provider == "openai" and _is_openai_too_large_error(exc):
            if progress_callback:
                progress_callback("OpenAI 单次上传超限，自动切换 Groq 分段识别...")
            result = transcribe_chunked(video_path, "groq", duration, progress_callback)
        else:
            raise

    if provider == "openai":
        _retry_low_confidence_with_groq(
            video_path, result["segments"],
            language=result.get("language", "unknown"),
            progress_callback=progress_callback,
        )

    result["segments"] = fix_timestamps(result["segments"])

    if segment_target:
        result["segments"] = normalize_segments(result["segments"], segment_target)

    return result


def transcribe_slice(audio_path, provider="groq", language=None):
    """识别一个音频切片，返回拼接后的完整文本。"""
    try:
        if provider == "azure":
            result = transcribe_azure_slice(audio_path, language)
        elif provider == "gemini":
            result = transcribe_gemini_slice(audio_path, language)
        elif provider == "openai":
            result = transcribe_openai(audio_path)
        elif provider == "qwen":
            result = qwen_provider.transcribe_file(audio_path)
        else:
            result = _transcribe_groq_wav(audio_path)
    except Exception as exc:
        if provider == "openai" and _is_openai_too_large_error(exc):
            result = _transcribe_groq_wav(audio_path)
        else:
            raise
    text = " ".join(seg["text"] for seg in result["segments"]).strip()
    return {"text": text, "language": result.get("language", "unknown")}


# ── 时间戳修复 / 断句归一化 ─────────────────────────────────────────────────────

def fix_timestamps(segments):
    if not segments:
        return segments
    fixed = []
    for seg in segments:
        seg      = dict(seg)
        start    = seg["start"]
        end      = seg["end"]
        text_len = len(seg.get("text", ""))
        min_dur  = max(1.0, text_len / 6.0)
        if end <= start:
            seg["end"] = round(start + min_dur, 2)
        elif (end - start) < min_dur * 0.3:
            seg["end"] = round(start + min_dur, 2)
        fixed.append(seg)
    for i in range(len(fixed) - 1):
        if fixed[i]["end"] > fixed[i + 1]["start"]:
            fixed[i]["end"] = fixed[i + 1]["start"]
    fixed.sort(key=lambda s: s["start"])
    for i, seg in enumerate(fixed):
        seg["index"] = i
    return fixed


def normalize_segments(segments, target_len):
    if not segments or target_len <= 0:
        return segments
    min_len = max(5, target_len // 3)
    max_len = target_len * 2
    merged  = []
    for seg in segments:
        if merged and len(merged[-1]["text"]) < min_len:
            prev = merged[-1]
            prev["text"] = prev["text"] + " " + seg["text"]
            prev["end"]  = seg["end"]
        elif merged and len(seg["text"]) < min_len:
            prev = merged[-1]
            prev["text"] = prev["text"] + " " + seg["text"]
            prev["end"]  = seg["end"]
        else:
            merged.append(dict(seg))
    result = []
    for seg in merged:
        text = seg["text"]
        if len(text) <= max_len:
            result.append(seg)
            continue
        duration      = seg["end"] - seg["start"]
        chars_per_sec = len(text) / duration if duration > 0 else 10
        chunks        = _split_text(text, target_len)
        chunk_start   = seg["start"]
        for chunk in chunks:
            chunk_dur = len(chunk) / chars_per_sec
            result.append({
                "text":  chunk,
                "start": round(chunk_start, 2),
                "end":   round(chunk_start + chunk_dur, 2),
            })
            chunk_start += chunk_dur
    for i, seg in enumerate(result):
        seg["index"] = i
    return result


def _split_text(text, target_len):
    chunks = []
    while len(text) > target_len * 1.5:
        split_pos    = target_len
        space_after  = text.find(" ", target_len)
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


# ── 泰语分词 / 词级时间戳 ──────────────────────────────────────────────────────

_TH_CUSTOM_WORDS = {
    "ฟอล", "ฟอลโล", "ฟอลโลเวอร์", "อันฟอลโล",
    "ไลก์", "ไลค์", "แชร์", "คอมเมนต์", "คอมเม้นต์",
    "โพสต์", "รีโพสต์", "รีทวีต", "แท็ก", "แบน", "บล็อก", "รีพอร์ต",
    "แฮชแท็ก", "ดีเอ็ม", "อินบ็อกซ์",
    "สตอรี่", "รีล", "รีลส์", "ฟีด", "ไลฟ์", "ไลฟ์สด",
    "สตรีม", "สตรีมมิ่ง", "คลิป", "คอนเทนต์", "แคปชั่น",
    "ฟิลเตอร์", "เซลฟี่", "เซลฟี", "สกรีนช็อต",
    "ยูทูบ", "ติ๊กตอก", "อินสตาแกรม", "เฟซบุ๊ก", "ทวิตเตอร์",
    "ดิสคอร์ด", "เรดดิต", "พินเทอเรสต์", "สแนปแชต",
    "ครีเอเตอร์", "อินฟลูเอนเซอร์", "ยูทูเบอร์", "ยูทูบเบอร์",
    "ติ๊กตอกเกอร์", "บล็อกเกอร์", "วล็อกเกอร์", "สตรีมเมอร์",
    "พอดแคสต์", "เน็ตไอดอล",
    "เทรนด์", "เทรนดิ้ง", "ไวรัล", "ดราม่า", "มีม", "ทัวร์ลง",
    "แคนเซิล", "ชาวเน็ต", "วาร์ป", "ไทม์ไลน์",
    "ไอดอล", "แฟนคลับ", "โอปป้า", "อุนนี่", "ออนนี่", "มาเน",
    "คัมแบ็ก", "ดีบิวต์", "เดบิวต์", "ออดิชั่น", "คอนเสิร์ต",
    "แฟนมีต", "แฟนไซน์", "คัฟเวอร์", "ชิปปิ้ง", "ไบอัส",
    "ซีรีส์", "ซีรีย์", "ทีเซอร์", "เอ็มวี", "เพลย์ลิสต์",
    "ไฟท์ติ้ง", "ฮวาอิติ้ง",
    "แบรนด์", "สปอนเซอร์", "คอลแลบ", "รีวิว", "พรีเซ็นเตอร์",
    "แอมบาสเดอร์", "โปรโมชั่น", "โปรโมต", "ดีล", "แคชแบ็ก",
    "ออเดอร์", "พรีออร์เดอร์", "ช้อปปี้", "ลาซาด้า", "ช้อปปิ้ง",
    "แอป", "แอพ", "ลิงก์", "อัปเดต", "อัพเดท", "อัปโหลด", "อัพโหลด",
    "ดาวน์โหลด", "ล็อกอิน", "ล็อกเอาท์", "แอคเคาน์",
    "ยูสเซอร์เนม", "โปรไฟล์", "อัลกอริทึม", "อัลกอ",
    "ไวไฟ", "บลูทูธ", "เน็ต", "วีพีเอ็น", "สแกมเมอร์",
    "ปัง", "ฟิน", "ชิล", "ชิลล์", "เฟล", "อิน", "มงลง",
    "โคตร", "แอบส่อง", "ฟีดหลุด", "โดนทัวร์ลง",
    "ไลฟ์สด", "คลิปไวรัล", "ข่าวเฟค", "ช้อปออนไลน์",
    "เรียนออนไลน์", "ทำงานรีโมท",
}

_th_trie = None


def _get_th_trie():
    global _th_trie
    if _th_trie is None:
        from pythainlp.corpus.common import thai_words
        from pythainlp.util import dict_trie
        combined = thai_words() | _TH_CUSTOM_WORDS
        _th_trie = dict_trie(combined)
    return _th_trie


def add_word_spacing(texts, language="th"):
    """用 PyThaiNLP 给泰语文本按词加空格。本地运行，非泰语原样返回。"""
    lang = (language or "")[:2].lower()
    if lang != "th" or not texts:
        return texts
    try:
        from pythainlp.tokenize import word_tokenize
        trie   = _get_th_trie()
        result = []
        for text in texts:
            if not text or not text.strip():
                result.append(text)
                continue
            words = word_tokenize(text, engine="newmm", custom_dict=trie, keep_whitespace=False)
            result.append(" ".join(w for w in words if w.strip()))
        return result
    except Exception as e:
        logger.warning(f"[WordSpacing] PyThaiNLP 失败: {e}，返回原文")
        return texts


def _alignment_tokens(text, language=None):
    """给时间戳对齐使用的 token 列表。

    - 泰语：优先按空格分词；没有空格时用 PyThaiNLP 断词
    - 其他语言：有空格按空格分；无空格按字符分
    """
    if not text:
        return []

    lang = (language or "")[:2].lower()
    if lang == "th":
        if " " in text:
            return [tk for tk in text.split() if tk.strip()]
        try:
            from pythainlp.tokenize import word_tokenize
            trie = _get_th_trie()
            return [tk for tk in word_tokenize(text, engine="newmm", custom_dict=trie, keep_whitespace=False) if tk.strip()]
        except Exception as e:
            logger.warning(f"[ThaiAlign] 断词失败: {e}，回退为整句 token")
            return [text]

    if " " in text:
        return [tk for tk in text.split() if tk.strip()]
    return [ch for ch in text if ch.strip()]


def align_word_timestamps(segments, groq_words, language=None):
    """把 word-level timestamps 对齐到分词后的每个句子。

    泰语会先做专用断词；其他语言保持原有策略。
    """
    if not groq_words:
        return
    lang = (language or "")[:2].lower()
    for seg in segments:
        text = seg.get("text", "")
        seg_start    = seg["start"]
        seg_end      = seg["end"]
        seg_gwords   = [w for w in groq_words
                        if w["start"] >= seg_start - 0.05 and w["end"] <= seg_end + 0.05]
        if not seg_gwords:
            continue
        tokens = _alignment_tokens(text, lang)
        if lang == "th" and (len(tokens) == 1 or tokens == [text]) and " " not in text:
            source_tokens = [w["word"] for w in seg_gwords if (w.get("word") or "").strip()]
            if source_tokens and "".join(source_tokens) == text.replace(" ", ""):
                tokens = source_tokens
        if not tokens:
            continue
        if lang != "th" and len(tokens) == 1 and " " not in text:
            # 非空格语言若只有一个 token，后续逐字对齐更稳
            tokens = [ch for ch in text if ch.strip()]
        gemini_chars    = list("".join(tokens))
        groq_chars      = []
        groq_char_times = []
        for gw in seg_gwords:
            for ch in gw["word"]:
                groq_chars.append(ch)
                groq_char_times.append((gw["start"], gw["end"]))
        timings = []
        gi = 0
        for gword in tokens:
            word_start = None
            word_end   = None
            for ch in gword:
                while gi < len(groq_chars) and groq_chars[gi] != ch:
                    gi += 1
                if gi < len(groq_chars):
                    t_start, t_end = groq_char_times[gi]
                    if word_start is None:
                        word_start = t_start
                    word_end = t_end
                    gi += 1
            if word_start is not None:
                timings.append({"start": round(word_start, 3), "end": round(word_end, 3)})
            else:
                timings = []
                break
        if timings and len(timings) == len(tokens):
            seg["wordTimings"] = timings


# ── Combined 校准算法 ────────────────────────────────────────────────────────────

_THAI_ABOVE = set("่้๊๋ิีึืุูัํ็์ำ")


def _thai_text_valid(text):
    consecutive = 0
    for ch in text:
        if ch in _THAI_ABOVE:
            consecutive += 1
            if consecutive > 2:
                return False
        else:
            consecutive = 0
    return True


def _groq_confidence(seg):
    lp = seg.get("_logprob")
    if lp is None:
        return 0.5
    ns = seg.get("_no_speech", 0)
    if ns > 0.5:
        return 0.1
    return round(max(0.0, min(1.0, 1.0 + lp)), 4)


def lcs_alignment(src, tgt):
    m, n = len(src), len(tgt)
    if m * n > 5_000_000:
        return _approx_alignment(src, tgt)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if src[i - 1] == tgt[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    pairs = []
    i, j  = m, n
    while i > 0 and j > 0:
        if src[i - 1] == tgt[j - 1]:
            pairs.append((i - 1, j - 1))
            i -= 1; j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def _approx_alignment(src, tgt):
    chunk_size = 50
    pairs      = []
    tgt_pos    = 0
    for start in range(0, len(src), chunk_size):
        chunk      = src[start:start + chunk_size]
        best_pos   = -1
        best_score = -1
        search_end = min(tgt_pos + len(chunk) * 3, len(tgt))
        for p in range(tgt_pos, max(tgt_pos, search_end - len(chunk) + 1)):
            score = sum(1 for a, b in zip(chunk, tgt[p:p + len(chunk)]) if a == b)
            if score > best_score:
                best_score = score
                best_pos   = p
        if best_pos >= 0 and best_score > len(chunk) * 0.3:
            for k, ch in enumerate(chunk):
                if best_pos + k < len(tgt) and ch == tgt[best_pos + k]:
                    pairs.append((start + k, best_pos + k))
            tgt_pos = best_pos + len(chunk)
    return pairs


def align_and_calibrate(groq_segments, azure_full_text, azure_segments=None):
    groq_full  = ""
    seg_ranges = []
    for seg in groq_segments:
        start = len(groq_full)
        groq_full += seg["text"]
        seg_ranges.append((start, len(groq_full)))

    if not groq_full or not azure_full_text:
        return groq_segments

    pairs = lcs_alignment(groq_full, azure_full_text)
    if not pairs:
        return groq_segments

    groq_to_azure = {g: a for g, a in pairs}

    seg_azure_starts = []
    for i, seg in enumerate(groq_segments):
        seg_start, seg_end = seg_ranges[i]
        first_azure = next((groq_to_azure[g] for g in range(seg_start, seg_end)
                            if g in groq_to_azure), None)
        seg_azure_starts.append(first_azure)

    az_conf_by_time = []
    if azure_segments:
        for az in azure_segments:
            az_conf_by_time.append({
                "start": az["start"], "end": az["end"],
                "conf":  az.get("_confidence", 0.5),
            })

    def get_azure_conf(t_start, t_end):
        if not az_conf_by_time:
            return 0.5
        confs = [az["conf"] for az in az_conf_by_time
                 if min(t_end, az["end"]) - max(t_start, az["start"]) > 0]
        return sum(confs) / len(confs) if confs else 0.5

    calibrated = []
    for i, seg in enumerate(groq_segments):
        a_start = seg_azure_starts[i]
        if a_start is None:
            seg = dict(seg)
            seg["_conf"]   = round(_groq_confidence(seg), 4)
            seg["_source"] = "groq"
            calibrated.append(seg)
            continue

        a_end = len(azure_full_text)
        for j in range(i + 1, len(groq_segments)):
            if seg_azure_starts[j] is not None:
                a_end = seg_azure_starts[j]
                break

        azure_slice = azure_full_text[a_start:a_end].strip()
        if not azure_slice:
            seg = dict(seg)
            seg["_conf"]   = round(_groq_confidence(seg), 4)
            seg["_source"] = "groq"
            calibrated.append(seg)
            continue

        groq_text = seg["text"]

        if not _thai_text_valid(azure_slice):
            logger.debug(f"[Calibrate] #{i} Azure 文本含无效泰语序列，保留 Groq: {azure_slice[:40]}")
            seg = dict(seg)
            seg["_conf"]   = round(_groq_confidence(seg), 4)
            seg["_source"] = "groq"
            calibrated.append(seg)
            continue

        if not _thai_text_valid(groq_text):
            logger.debug(f"[Calibrate] #{i} Groq 文本含无效泰语序列，用 Azure: {groq_text[:40]}")
            seg = dict(seg)
            seg["text"]    = azure_slice
            seg["_conf"]   = round(get_azure_conf(seg["start"], seg["end"]), 4)
            seg["_source"] = "azure"
            calibrated.append(seg)
            continue

        groq_conf  = _groq_confidence(seg)
        azure_conf = get_azure_conf(seg["start"], seg["end"])
        lcs_pairs  = lcs_alignment(groq_text, azure_slice)
        lcs_ratio  = len(lcs_pairs) / max(len(groq_text), len(azure_slice), 1)

        seg = dict(seg)
        if lcs_ratio < 0.3:
            logger.debug(f"[Calibrate] #{i} 差异过大(lcs={lcs_ratio:.2f})，保留 Groq")
            seg["_conf"]   = round(groq_conf, 4)
            seg["_source"] = "groq"
        elif lcs_ratio > 0.9:
            if azure_conf >= groq_conf:
                seg["text"]    = azure_slice
                seg["_conf"]   = round(azure_conf, 4)
                seg["_source"] = "azure"
            else:
                seg["_conf"]   = round(groq_conf, 4)
                seg["_source"] = "groq"
        elif azure_conf > groq_conf + 0.1:
            seg["text"]    = azure_slice
            seg["_conf"]   = round(azure_conf, 4)
            seg["_source"] = "azure"
        else:
            seg["_conf"]   = round(groq_conf, 4)
            seg["_source"] = "groq"

        calibrated.append(seg)
    return calibrated


def fill_gaps_with_azure(groq_segments, azure_segments, gap_threshold=1.0):
    if not azure_segments or not groq_segments:
        return groq_segments
    merged  = list(groq_segments)
    inserts = []
    for i in range(len(merged) - 1):
        gap_start = merged[i]["end"]
        gap_end   = merged[i + 1]["start"]
        if gap_end - gap_start < gap_threshold:
            continue
        for az_seg in azure_segments:
            az_mid = (az_seg["start"] + az_seg["end"]) / 2
            if gap_start - 0.5 <= az_mid <= gap_end + 0.5:
                inserts.append({
                    "text":  az_seg["text"],
                    "start": max(az_seg["start"], gap_start),
                    "end":   min(az_seg["end"],   gap_end),
                })
    if inserts:
        merged.extend(inserts)
        merged.sort(key=lambda s: s["start"])
        for i, seg in enumerate(merged):
            seg["index"] = i
    return merged
