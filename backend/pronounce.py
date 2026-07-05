import os
import json
import subprocess
import azure.cognitiveservices.speech as speechsdk


def convert_to_wav(input_path, output_path):
    """将浏览器录制的 webm/ogg 音频转为 Azure 要求的 WAV 格式（16kHz 单声道）"""
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-ar", "16000",
        "-ac", "1",
        "-sample_fmt", "s16",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"音频转换失败: {result.stderr[-300:]}")


def assess_pronunciation(audio_path, reference_text, language="th-TH"):
    """
    调用 Azure Speech Pronunciation Assessment 对音频进行发音评估。
    返回：{
        overall_score: 总分(0-100),
        accuracy_score: 准确度,
        fluency_score: 流利度,
        completeness_score: 完整度,
        words: [{ word, accuracy_score, error_type }, ...]
    }
    """
    speech_key = os.environ.get("AZURE_SPEECH_KEY", "")
    speech_region = os.environ.get("AZURE_SPEECH_REGION", "")

    if not speech_key or not speech_region:
        raise RuntimeError("请在 .env 中配置 AZURE_SPEECH_KEY 和 AZURE_SPEECH_REGION")

    # 转换音频格式
    wav_path = audio_path + ".wav"
    convert_to_wav(audio_path, wav_path)

    try:
        # 配置 Speech
        speech_config = speechsdk.SpeechConfig(
            subscription=speech_key, region=speech_region
        )
        speech_config.speech_recognition_language = language

        # 配置发音评估
        pronunciation_config = speechsdk.PronunciationAssessmentConfig(
            reference_text=reference_text,
            grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
            granularity=speechsdk.PronunciationAssessmentGranularity.Word,
            enable_miscue=True,
        )

        # 音频输入
        audio_config = speechsdk.audio.AudioConfig(filename=wav_path)

        # 创建识别器并执行评估
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config, audio_config=audio_config
        )
        pronunciation_config.apply_to(recognizer)

        result = recognizer.recognize_once_async().get()

        print(f"[Pronounce] language={language}, ref_text={reference_text[:50]}")
        print(f"[Pronounce] result.reason={result.reason}, text={result.text if hasattr(result, 'text') else 'N/A'}")

        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            pron_result = speechsdk.PronunciationAssessmentResult(result)

            print(f"[Pronounce] scores: pron={pron_result.pronunciation_score}, "
                  f"acc={pron_result.accuracy_score}, flu={pron_result.fluency_score}, "
                  f"comp={pron_result.completeness_score}")

            # 提取每个词的评分
            words = []
            if pron_result.words:
                for word in pron_result.words:
                    words.append({
                        "word": word.word,
                        "accuracy_score": word.accuracy_score,
                        "error_type": word.error_type,
                    })

            return {
                "recognized_text": result.text,
                "overall_score": pron_result.pronunciation_score or 0,
                "accuracy_score": pron_result.accuracy_score or 0,
                "fluency_score": pron_result.fluency_score or 0,
                "completeness_score": pron_result.completeness_score or 0,
                "words": words,
            }

        elif result.reason == speechsdk.ResultReason.NoMatch:
            return {
                "recognized_text": "",
                "overall_score": 0,
                "accuracy_score": 0,
                "fluency_score": 0,
                "completeness_score": 0,
                "words": [],
                "error": "未能识别语音，请重新录音",
            }
        else:
            cancellation = result.cancellation_details
            raise RuntimeError(
                f"语音识别失败: {cancellation.reason} - {cancellation.error_details}"
            )
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)
