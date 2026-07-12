"""
Youdao Confucius TTS Provider
有道子曰 TTS 演示端点（Gradio 会话协议 + 声音克隆）。
声音克隆：按性别用预置参考音频建会话，同会话内逐句合成。
"""
import json
import os
import subprocess
import requests as _requests
from config import providers, settings, get_logger

logger = get_logger(__name__)

YOUDAO_BASE = providers.Youdao.BASE_URL
ASSETS_DIR  = settings.ASSETS_DIR
YOUDAO_REFS = {"male": "ref_thai_male.wav", "female": "ref_thai_female.wav"}


class YoudaoTTS:
    """有道子曰 TTS：按性别建立 Gradio 会话，参考音频仅预处理一次。"""

    def __init__(self):
        self.sessions = {}  # gender -> (session_hash, file_data)

    def _run(self, session, fn_index, trigger_id, data, timeout=settings.TIMEOUT_YOUDAO_DEFAULT):
        r = _requests.post(f"{YOUDAO_BASE}/queue/join", json={
            "data": data, "event_data": None, "fn_index": fn_index,
            "trigger_id": trigger_id, "session_hash": session,
        }, timeout=settings.TIMEOUT_YOUDAO_QUEUE)
        if r.status_code != 200:
            raise RuntimeError(f"有道 TTS 排队失败 {r.status_code}")
        with _requests.get(
            f"{YOUDAO_BASE}/queue/data?session_hash={session}",
            stream=True, timeout=timeout
        ) as resp:
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
            r = _requests.post(
                f"{YOUDAO_BASE}/upload",
                files={"files": ("ref.wav", f, "audio/wav")},
                timeout=settings.TIMEOUT_YOUDAO_UPLOAD,
            )
        if r.status_code != 200:
            raise RuntimeError(f"参考音频上传失败 {r.status_code}")
        path  = r.json()[0]
        fdata = {
            "path": path, "url": f"{YOUDAO_BASE}/file={path}",
            "orig_name": "ref.wav", "size": os.path.getsize(ref_file),
            "mime_type": "audio/wav", "meta": {"_type": "gradio.FileData"},
        }
        session = secrets.token_hex(8)
        self._run(session, 0, 6, [fdata], timeout=settings.TIMEOUT_YOUDAO_SESSION)
        self.sessions[gender] = (session, fdata)

    def tts_sentence(self, text, language, gender, out_path):
        """合成单句语音，写入 24kHz 单声道 16-bit WAV 文件。"""
        self._ensure_session(gender)
        session, fdata = self.sessions[gender]
        out  = self._run(session, 1, 9, [text, language, fdata, None])
        data = out.get("data")
        if not data or not data[0]:
            raise RuntimeError(f"有道 TTS 合成失败: {str(data)[:120]}")
        audio = _requests.get(data[0]["url"], timeout=settings.TIMEOUT_YOUDAO_AUDIO).content
        tmp   = out_path + ".dl"
        with open(tmp, "wb") as f:
            f.write(audio)
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", tmp, "-ar", "24000", "-ac", "1", "-sample_fmt", "s16", out_path],
            capture_output=True, text=True,
        )
        os.remove(tmp)
        if r.returncode != 0:
            raise RuntimeError("有道音频转换失败: " + r.stderr[-150:])
