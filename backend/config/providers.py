"""
Provider 级别配置：各第三方服务的 Base URL、固定模型名、声音表。

依赖 settings 中读取的 API Key 和可被环境变量覆盖的模型名。
"""
from config import settings


class Groq:
    API_KEY       = settings.GROQ_API_KEY
    BASE_URL      = "https://api.groq.com/openai/v1"
    WHISPER_MODEL = "whisper-large-v3"


class OpenAI:
    API_KEY       = settings.OPENAI_API_KEY
    WHISPER_MODEL = "whisper-1"


class Gemini:
    API_KEY    = settings.GEMINI_API_KEY
    BASE_V1    = "https://generativelanguage.googleapis.com/v1"
    BASE_V1BETA = "https://generativelanguage.googleapis.com/v1beta"
    # URL 模板（{model} 和 {key} 由调用方填充）
    URL_V1     = BASE_V1    + "/models/{model}:generateContent?key={key}"
    URL_V1BETA = BASE_V1BETA + "/models/{model}:generateContent?key={key}"
    # 模型名（可通过环境变量覆盖的在 settings；固定的在这里）
    TEXT_MODEL     = settings.GEMINI_TEXT_MODEL
    TTS_MODEL      = settings.GEMINI_TTS_MODEL
    IMAGE_MODEL    = settings.GEMINI_IMAGE_MODEL
    ROMANIZE_MODEL = "gemini-3.5-flash"


class DeepSeek:
    API_KEY  = settings.DEEPSEEK_API_KEY
    BASE_URL = "https://api.deepseek.com/chat/completions"
    MODEL    = "deepseek-chat"


class Azure:
    SPEECH_KEY    = settings.AZURE_SPEECH_KEY
    SPEECH_REGION = settings.AZURE_SPEECH_REGION


class R2:
    ACCOUNT_ID        = settings.R2_ACCOUNT_ID
    ACCESS_KEY_ID     = settings.R2_ACCESS_KEY_ID
    SECRET_ACCESS_KEY = settings.R2_SECRET_ACCESS_KEY
    BUCKET_NAME       = settings.R2_BUCKET_NAME
    PUBLIC_URL        = settings.R2_PUBLIC_URL
    ENDPOINT_URL      = (
        f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        if settings.R2_ACCOUNT_ID else ""
    )


class Youdao:
    BASE_URL = "https://confucius4-tts.youdao.com/gradio"
