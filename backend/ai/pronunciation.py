"""
发音评估服务层
业务模块通过 assess_pronunciation() 调用，不知道底层是 Azure。
保持与原 pronounce.py 完全相同的函数签名和返回格式。
"""
import os
import subprocess
from config import get_logger
from ai.provider import azure as azure_provider

logger = get_logger(__name__)


def _convert_to_wav(input_path, output_path):
    """将浏览器录制的 webm/ogg 音频转为 Azure 要求的 WAV 格式（16kHz 单声道）"""
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"音频转换失败: {result.stderr[-300:]}")


def assess_pronunciation(audio_path, reference_text, language="th-TH"):
    """对录音进行发音评估。

    Args:
        audio_path: 浏览器录制的音频文件（webm/ogg/wav）
        reference_text: 参考文本
        language: BCP-47 语言代码（如 "th-TH"）
    Returns:
        {overall_score, accuracy_score, fluency_score, completeness_score,
         recognized_text, words: [{word, accuracy_score, error_type}]}
    """
    wav_path = audio_path + ".wav"
    _convert_to_wav(audio_path, wav_path)

    wav_size = os.path.getsize(wav_path) if os.path.exists(wav_path) else 0
    logger.debug(f"[Pronounce] wav_size={wav_size} bytes, language={language}")
    logger.debug(f"[Pronounce] reference_text={reference_text[:80]}")

    if wav_size < 1000:
        raise RuntimeError("录音太短，请重新录音")

    try:
        return azure_provider.assess_pronunciation(wav_path, reference_text, language)
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)
