"""
Azure Speech Provider
唯一职责：Azure Speech SDK 的 ASR（识别）、TTS（合成）、发音评估三类调用。
每个函数只做 API 调用和直接解析，业务逻辑由上层 service 处理。
"""
import json
import threading
from config import providers, settings, get_logger

logger = get_logger(__name__)

LOCALE_MAP = {
    "th": "th-TH", "en": "en-US", "ja": "ja-JP", "ko": "ko-KR",
    "fr": "fr-FR", "de": "de-DE", "es": "es-ES", "pt": "pt-BR",
    "ru": "ru-RU", "it": "it-IT", "zh": "zh-CN", "vi": "vi-VN", "hi": "hi-IN",
}


def _check_credentials():
    key    = providers.Azure.SPEECH_KEY
    region = providers.Azure.SPEECH_REGION
    if not key or not region:
        raise RuntimeError("请在 .env 中配置 AZURE_SPEECH_KEY 和 AZURE_SPEECH_REGION")
    return key, region


# ── ASR ────────────────────────────────────────────────────────────────────────

def transcribe_full(wav_path):
    """连续识别整段 WAV 音频（自动检测语言）。

    Returns:
        {"segments": [{"text", "start", "end", "_confidence"?, "index"}, ...],
         "language": "th" | "en" | ...}
    """
    import azure.cognitiveservices.speech as speechsdk

    key, region = _check_credentials()
    speech_cfg = speechsdk.SpeechConfig(subscription=key, region=region)
    speech_cfg.output_format = speechsdk.OutputFormat.Detailed

    auto_detect = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
        languages=["th-TH", "en-US", "ja-JP", "ko-KR", "fr-FR", "de-DE",
                   "es-ES", "pt-BR", "ru-RU", "it-IT"]
    )
    audio_cfg  = speechsdk.audio.AudioConfig(filename=wav_path)
    recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_cfg,
        audio_config=audio_cfg,
        auto_detect_source_language_config=auto_detect,
    )

    segments     = []
    done_event   = threading.Event()
    detected_lang = "unknown"

    def on_recognized(evt):
        nonlocal detected_lang
        if evt.result.reason != speechsdk.ResultReason.RecognizedSpeech:
            return
        text = evt.result.text.strip()
        if not text:
            return
        offset_s   = evt.result.offset / 10_000_000
        duration_s = evt.result.duration / 10_000_000
        seg = {
            "text":  text,
            "start": round(offset_s, 2),
            "end":   round(offset_s + duration_s, 2),
        }
        try:
            detail = json.loads(evt.result.json)
            nbest  = detail.get("NBest", [])
            if nbest:
                seg["_confidence"] = round(nbest[0].get("Confidence", 0), 4)
        except Exception:
            pass
        segments.append(seg)
        lang_res = speechsdk.AutoDetectSourceLanguageResult(evt.result)
        lang = lang_res.language
        if lang and lang != "Unknown":
            detected_lang = lang

    def on_canceled(evt):
        if evt.cancellation_details.reason == speechsdk.CancellationReason.Error:
            logger.error(f"Azure Speech 错误: {evt.cancellation_details.error_details}")
        done_event.set()

    recognizer.recognized.connect(on_recognized)
    recognizer.session_stopped.connect(lambda evt: done_event.set())
    recognizer.canceled.connect(on_canceled)

    recognizer.start_continuous_recognition()
    done_event.wait(timeout=settings.TIMEOUT_AZURE_RECOGNITION)
    recognizer.stop_continuous_recognition()

    for i, seg in enumerate(segments):
        seg["index"] = i

    lang_map = {
        "th-TH": "th", "en-US": "en", "ja-JP": "ja", "ko-KR": "ko",
        "fr-FR": "fr", "de-DE": "de", "es-ES": "es", "pt-BR": "pt",
        "ru-RU": "ru", "it-IT": "it",
    }
    language = lang_map.get(detected_lang, detected_lang)
    return {"segments": segments, "language": language}


def transcribe_slice(wav_path, language=None):
    """单次识别短音频（明确指定语言，不做自动检测）。

    Returns:
        {"segments": [...], "language": "th" | "en" | ...}
    """
    import azure.cognitiveservices.speech as speechsdk

    key, region = _check_credentials()
    short  = (language or "en")[:2].lower()
    locale = LOCALE_MAP.get(short, "en-US")

    speech_cfg = speechsdk.SpeechConfig(subscription=key, region=region)
    speech_cfg.speech_recognition_language = locale
    audio_cfg  = speechsdk.audio.AudioConfig(filename=wav_path)
    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_cfg, audio_config=audio_cfg)

    segments   = []
    done_event = threading.Event()

    def on_recognized(evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            text = evt.result.text.strip()
            if text:
                offset_s   = evt.result.offset / 10_000_000
                duration_s = evt.result.duration / 10_000_000
                segments.append({
                    "text":  text,
                    "start": round(offset_s, 2),
                    "end":   round(offset_s + duration_s, 2),
                })

    def on_canceled(evt):
        if evt.cancellation_details.reason == speechsdk.CancellationReason.Error:
            logger.error(f"Azure Slice 错误: {evt.cancellation_details.error_details}")
        done_event.set()

    recognizer.recognized.connect(on_recognized)
    recognizer.session_stopped.connect(lambda evt: done_event.set())
    recognizer.canceled.connect(on_canceled)

    recognizer.start_continuous_recognition()
    done_event.wait(timeout=settings.TIMEOUT_AZURE_SLICE)
    recognizer.stop_continuous_recognition()

    for i, seg in enumerate(segments):
        seg["index"] = i

    return {"segments": segments, "language": short}


# ── TTS ────────────────────────────────────────────────────────────────────────

def tts(text, voice_name, out_path):
    """Azure Neural TTS 合成音频并写入文件（Riff24Khz16BitMonoPcm WAV）。

    Args:
        text: 要合成的文本
        voice_name: 完整声音名称，如 "th-TH-PremwadeeNeural"
        out_path: 输出 WAV 文件路径
    Raises:
        RuntimeError: TTS 失败
    """
    import azure.cognitiveservices.speech as speechsdk

    key, region = _check_credentials()
    speech_cfg = speechsdk.SpeechConfig(subscription=key, region=region)
    speech_cfg.speech_synthesis_voice_name = voice_name
    speech_cfg.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm
    )
    audio_cfg = speechsdk.audio.AudioOutputConfig(filename=out_path)
    synth     = speechsdk.SpeechSynthesizer(speech_config=speech_cfg, audio_config=audio_cfg)
    result    = synth.speak_text_async(text).get()

    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        detail = ""
        if result.reason == speechsdk.ResultReason.Canceled:
            detail = result.cancellation_details.error_details
        raise RuntimeError(f"Azure TTS 失败: {detail}")


# ── Pronunciation Assessment ────────────────────────────────────────────────────

def assess_pronunciation(wav_path, reference_text, language="th-TH"):
    """发音评估，返回评分字典。

    Returns:
        {recognized_text, overall_score, accuracy_score, fluency_score,
         completeness_score, words: [{word, accuracy_score, error_type}]}
        失败时 overall_score=0，可能含 "error" 字段。
    Raises:
        RuntimeError: 识别被取消或未知状态
    """
    import azure.cognitiveservices.speech as speechsdk

    key, region = _check_credentials()
    speech_cfg  = speechsdk.SpeechConfig(subscription=key, region=region)
    speech_cfg.speech_recognition_language = language

    use_miscue = language.startswith("en")
    pron_cfg   = speechsdk.PronunciationAssessmentConfig(
        reference_text=reference_text,
        grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
        granularity=speechsdk.PronunciationAssessmentGranularity.Word,
        enable_miscue=use_miscue,
    )
    audio_cfg  = speechsdk.audio.AudioConfig(filename=wav_path)
    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_cfg, audio_config=audio_cfg)
    pron_cfg.apply_to(recognizer)
    result = recognizer.recognize_once_async().get()

    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        pron  = speechsdk.PronunciationAssessmentResult(result)
        words = []
        if pron.words:
            for w in pron.words:
                words.append({
                    "word": w.word,
                    "accuracy_score": w.accuracy_score,
                    "error_type": w.error_type,
                })
        return {
            "recognized_text":    result.text,
            "overall_score":      pron.pronunciation_score or 0,
            "accuracy_score":     pron.accuracy_score or 0,
            "fluency_score":      pron.fluency_score or 0,
            "completeness_score": pron.completeness_score or 0,
            "words":              words,
        }
    elif result.reason == speechsdk.ResultReason.NoMatch:
        return {
            "recognized_text": "", "overall_score": 0,
            "accuracy_score": 0, "fluency_score": 0, "completeness_score": 0,
            "words": [],
            "error": f"未能识别语音（语言: {language}），请靠近麦克风重新录音",
        }
    elif result.reason == speechsdk.ResultReason.Canceled:
        c = result.cancellation_details
        raise RuntimeError(f"语音识别失败: {c.reason} - {c.error_details}")
    else:
        raise RuntimeError(f"语音识别返回未知状态: {result.reason}")
