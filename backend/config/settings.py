"""
统一配置入口。

所有环境变量、路径、超时常量在此统一读取。
其他模块不得直接调用 os.getenv() 或硬编码路径/URL。
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# ── 目录基准 ──────────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).parent.parent   # backend/
PROJECT_DIR = BACKEND_DIR.parent             # videoplayer/

load_dotenv(BACKEND_DIR / ".env")

# ── 路径 ──────────────────────────────────────────────────────────────────────
VIDEOS_DIR      = str(PROJECT_DIR / "videos")
FRONTEND_DIR    = str(PROJECT_DIR / "frontend")
EXPORTS_DIR     = str(PROJECT_DIR / "exports")
TMP_DIR         = str(BACKEND_DIR / "tmp")
ASSETS_DIR      = str(BACKEND_DIR / "assets")
USAGE_LOG       = str(PROJECT_DIR / "videos" / "usage_log.jsonl")
YT_COOKIES_FILE = str(BACKEND_DIR / ".yt_cookies.txt")

# macOS 字体候选路径（export.py 使用）
FONT_SEARCH_PATHS = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
]

# ── API Keys ──────────────────────────────────────────────────────────────────
ADMIN_KEY           = os.getenv("ADMIN_KEY", "")
GROQ_API_KEY        = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY")
AZURE_SPEECH_KEY    = os.getenv("AZURE_SPEECH_KEY", "")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "")
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY", "")
DEEPSEEK_API_KEY    = os.getenv("DEEPSEEK_API_KEY")
YOUTUBE_COOKIES     = os.getenv("YOUTUBE_COOKIES", "")

# ── R2 对象存储 ───────────────────────────────────────────────────────────────
R2_ACCOUNT_ID       = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID    = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME      = os.getenv("R2_BUCKET_NAME", "reelspeak-audio")
R2_PUBLIC_URL       = os.getenv("R2_PUBLIC_URL", "")

# ── Cloudflare Workers AI ─────────────────────────────────────────────────────
CF_AI_API_TOKEN     = os.getenv("CF_AI_API_TOKEN", "")   # Workers AI 专用 Token

# ── 服务器 ────────────────────────────────────────────────────────────────────
PORT = int(os.getenv("PORT", "5000"))

# ── 可通过环境变量覆盖的模型名 ────────────────────────────────────────────────
GEMINI_TEXT_MODEL  = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
GEMINI_TTS_MODEL   = os.getenv("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview")
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-lite-image")

# ── 日志控制 ──────────────────────────────────────────────────────────────────
DEBUG    = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")
LOG_FILE = os.getenv("LOG_FILE", "")   # 空 = 不写文件

# ── 超时（秒） ────────────────────────────────────────────────────────────────
TIMEOUT_FFPROBE           = 15
TIMEOUT_FFMPEG_NORMALIZE  = 300
TIMEOUT_YTDLP             = 30
TIMEOUT_OPENAI            = 300.0
TIMEOUT_GROQ              = 60.0
TIMEOUT_AZURE_RECOGNITION = 300
TIMEOUT_AZURE_SLICE       = 120
TIMEOUT_GEMINI_DEFAULT    = 60
TIMEOUT_GEMINI_TTS        = 120
TIMEOUT_GEMINI_COVER      = 90
TIMEOUT_GEMINI_TEST       = 20
TIMEOUT_GEMINI_MODELS     = 10
TIMEOUT_DEEPSEEK          = 15
TIMEOUT_TRANSLATE         = 30
TIMEOUT_ROMANIZE          = 30
TIMEOUT_WORD_DEFINE       = 15
TIMEOUT_YOUDAO_DEFAULT    = 300
TIMEOUT_YOUDAO_QUEUE      = 30
TIMEOUT_YOUDAO_UPLOAD     = 60
TIMEOUT_YOUDAO_SESSION    = 120
TIMEOUT_YOUDAO_AUDIO      = 60
