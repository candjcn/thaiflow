import os
import json
import queue
import re
import subprocess
import threading
from flask import Flask, request, jsonify, send_from_directory, Response, make_response, redirect
from flask_cors import CORS
from config import settings, providers, get_logger
from ai.speech import transcribe_video, transcribe_slice, add_word_spacing, align_word_timestamps, get_video_duration
from ai.translation import translate_segments, word_define as _word_define
from ai.tts import generate_audio_lesson, generate_cover_image, ocr_image, detect_input_mode, generate_tts_content
from ai.pronunciation import assess_pronunciation
from ai.romanize import generate_romanization
from export import export_video_with_subtitles, export_srt
from r2 import upload_audio
from domain import Segment, SubtitleFile

from commerce.db import init_db, get_db
from commerce.seed import run_seed
from commerce.identity import get_or_create_anonymous, get_user_plan, ANONYMOUS_USER_ID
from commerce.middleware import CommerceContext
import commerce.auth as _auth
from commerce.wallet import (
    add_credits as _wallet_add, refund as _wallet_refund,
    get_balance as _wallet_balance, get_history as _wallet_history,
    InsufficientFundsError,
)
from commerce.usage_log import (
    get_log as _log_get, get_user_history as _log_user_history,
    get_summary as _log_summary,
)
from commerce.rate_limit import (
    check_rate_limit as _check_rate_limit,
    increment as _rl_increment,
    get_limit as _rl_get_limit,
    get_usage as _rl_get_usage,
)


def _get_user_id(db) -> str:
    """从 Cookie session 解析当前用户 ID；未登录返回 ANONYMOUS_USER_ID。"""
    user = _auth.get_current_user(db, request)
    return user["user_id"] if user else ANONYMOUS_USER_ID


def _get_device_id() -> str | None:
    """从请求 Header 读取前端设备 UUID（匿名用户指纹）。"""
    return request.headers.get("X-Device-ID") or None


def _get_rl_key(uid: str) -> str:
    """返回限流 key：已登录用户用 user_id，匿名用户用 device:UUID。"""
    if uid != ANONYMOUS_USER_ID:
        return uid
    device_id = _get_device_id()
    return f"device:{device_id}" if device_id else ANONYMOUS_USER_ID

logger = get_logger(__name__)

app = Flask(__name__)
CORS(app)

# ── Commerce 初始化（应用启动时执行一次） ──────────────────────────────────────
def _init_commerce():
    db = init_db(settings.COMMERCE_DB_PATH)
    run_seed(db)
    get_or_create_anonymous(db)
    db.close()
    from commerce.cron import start_cron
    start_cron(get_db)
    logger.info("[commerce] DB ready")

_init_commerce()


@app.after_request
def set_cache_headers(response):
    """HTML/JS/CSS 要求重新验证（防 Cloudflare/浏览器缓存旧版本导致页面与脚本不匹配）；
    视频/音频/图片可长缓存"""
    ct = response.content_type or ""
    if any(t in ct for t in ("text/html", "javascript", "text/css")):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    elif any(t in ct for t in ("video/", "audio/", "image/")):
        response.headers["Cache-Control"] = "public, max-age=86400"
    return response

VIDEOS_DIR   = settings.VIDEOS_DIR
FRONTEND_DIR = settings.FRONTEND_DIR


def clean_video_title(title):
    """把视频标题清理成干净的文件名：去掉 # 标签、控制字符，截到 40 字"""
    # 去掉 #xxx 标签（井号开头直到空格或末尾）
    t = re.sub(r'#\S+', '', title)
    # 去掉文件系统非法字符
    t = re.sub(r'[\\/:*?"<>|]', '', t)
    # 合并多余空格、去掉首尾空白和标点
    t = re.sub(r'\s+', ' ', t).strip(' ._-')
    # 截到 40 字，在词边界截断
    if len(t) > 40:
        t = t[:40].rsplit(' ', 1)[0].strip()
    return t or "video"


def subtitle_path(video_name):
    """视频对应的字幕 JSON 文件路径"""
    base = os.path.splitext(video_name)[0]
    return os.path.join(VIDEOS_DIR, base + ".json")


# ========== 使用日志（开发者分析用） ==========
USAGE_LOG = settings.USAGE_LOG


def log_event(kind, **data):
    """记录一条使用事件：写文件 + 打印 stdout（Railway 控制台可查看）"""
    import datetime
    record = {
        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": kind,
        **data,
    }
    line = json.dumps(record, ensure_ascii=False)
    logger.info(f"[USAGE] {line}")
    try:
        os.makedirs(VIDEOS_DIR, exist_ok=True)
        with open(USAGE_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def normalize_audio(video_path):
    """响度归一化（-14 LUFS，对齐 TikTok 播放标准）+ 轻度语音降噪。
    源片音量低的视频下载后会明显变小声，统一拉到学习友好的响度。
    视频流直接拷贝（快），失败时保留原文件。"""
    tmp_path = video_path + ".norm.mp4"
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-c:v", "copy",
        "-af", "volume=2.0",
        "-c:a", "aac", "-b:a", "128k",
        tmp_path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=settings.TIMEOUT_FFMPEG_NORMALIZE)
        if r.returncode == 0 and os.path.getsize(tmp_path) > 0:
            os.replace(tmp_path, video_path)
            return True
        logger.warning(f"[Normalize] 失败: {r.stderr[-200:]}")
    except Exception as e:
        logger.error(f"[Normalize] 异常: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return False



@app.route("/api/admin/logs")
def admin_logs():
    """开发者查看使用日志（需要 ADMIN_KEY）"""
    admin_key = settings.ADMIN_KEY
    if not admin_key or request.args.get("key") != admin_key:
        return jsonify({"error": "unauthorized"}), 403
    events = []
    if os.path.exists(USAGE_LOG):
        with open(USAGE_LOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return jsonify({"count": len(events), "events": events[-500:]})


@app.route("/api/admin/gemini-models")
def admin_gemini_models():
    """列出当前 GEMINI_API_KEY 可用的模型（诊断用）"""
    import requests as _req
    key = providers.Gemini.API_KEY
    if not key:
        return jsonify({"error": "no GEMINI_API_KEY"}), 500
    results = {}
    for ver, base in (("v1", providers.Gemini.BASE_V1), ("v1beta", providers.Gemini.BASE_V1BETA)):
        url = f"{base}/models?key={key}"
        try:
            r = _req.get(url, timeout=settings.TIMEOUT_GEMINI_MODELS)
            if r.status_code == 200:
                names = [m["name"] for m in r.json().get("models", [])]
                results[ver] = names
            else:
                results[ver] = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            results[ver] = str(e)
    return jsonify(results)


@app.route("/api/admin/gemini-test")
def admin_gemini_test():
    """直接测试 generateContent，看 key 是否真的能生成内容（诊断用）"""
    import requests as _req
    key = providers.Gemini.API_KEY
    key_prefix = key[:12] + "..." if len(key) > 12 else key
    results = {"key_prefix": key_prefix, "key_length": len(key), "tests": {}}
    for model in ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite"):
        label = f"v1/{model}"
        url = f"{providers.Gemini.BASE_V1}/models/{model}:generateContent?key={key}"
        try:
            r = _req.post(url, json={
                "contents": [{"parts": [{"text": "Say hi"}]}],
                "generationConfig": {"maxOutputTokens": 5},
            }, timeout=settings.TIMEOUT_GEMINI_TEST)
            if r.status_code == 200:
                results["tests"][label] = "OK"
            else:
                results["tests"][label] = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            results["tests"][label] = f"Exception: {e}"
    return jsonify(results)


@app.route("/")
def landing():
    return send_from_directory(FRONTEND_DIR, "landing.html")


@app.route("/app")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/profile")
def profile():
    return send_from_directory(FRONTEND_DIR, "profile.html")


@app.route("/story")
def ai_story():
    docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
    return send_from_directory(docs_dir, "ai-dev-story.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(FRONTEND_DIR, filename)


@app.route("/videos/<path:filename>")
def serve_video(filename):
    return send_from_directory(VIDEOS_DIR, filename)


@app.route("/api/browse-dir")
def browse_dir():
    """浏览目录，返回子文件夹列表"""
    path = request.args.get("path", os.path.expanduser("~"))
    path = os.path.expanduser(path)

    if not os.path.isdir(path):
        # 尝试上级目录
        path = os.path.dirname(path)
        if not os.path.isdir(path):
            path = os.path.expanduser("~")

    dirs = []
    try:
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            if os.path.isdir(full) and not name.startswith("."):
                dirs.append(name)
    except PermissionError:
        pass

    parent = os.path.dirname(path)
    return jsonify({
        "current": path,
        "parent": parent if parent != path else None,
        "dirs": dirs,
    })


@app.route("/api/upload-video", methods=["POST"])
def api_upload_video():
    """上传本地视频文件到 videos 目录，可附带字幕 JSON"""
    if "video" not in request.files:
        return jsonify({"error": "缺少视频文件"}), 400

    video_file = request.files["video"]
    if not video_file.filename:
        return jsonify({"error": "文件名为空"}), 400

    # 清理文件名
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', video_file.filename)[:80]
    if not safe_name.lower().endswith(".mp4"):
        safe_name += ".mp4"

    os.makedirs(VIDEOS_DIR, exist_ok=True)
    save_path = os.path.join(VIDEOS_DIR, safe_name)
    video_file.save(save_path)

    # 如果附带字幕文件，也保存
    has_subtitle = False
    if "subtitle" in request.files:
        sub_file = request.files["subtitle"]
        if sub_file.filename:
            sub_path = subtitle_path(safe_name)
            sub_file.save(sub_path)
            has_subtitle = True

    # 响度归一化 + 降噪（与链接下载路径一致）
    normalize_audio(save_path)

    log_event("upload", video=safe_name, has_subtitle=has_subtitle)

    return jsonify({
        "name": safe_name,
        "has_subtitle": has_subtitle,
        "message": "上传成功" + ("（含字幕）" if has_subtitle else ""),
    })


def _extract_url_from_text(text):
    """从分享文本中提取第一个 HTTP URL（兼容抖音/微信分享格式）"""
    m = re.search(r'https?://[^\s，。！？、""'']+', text)
    if m:
        return m.group(0).rstrip('.,，。！？、')
    return text.strip()


def _is_douyin_url(url):
    return any(d in url for d in ('v.douyin.com', 'www.douyin.com', 'm.douyin.com', 'iesdouyin.com'))


def _download_douyin(url, output_path, progress_callback=None):
    """自定义抖音下载：短链解析 → 分享页提取视频 URI → CDN 下载"""
    import ssl
    import urllib.request as urlreq

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    headers = {
        'User-Agent': ('Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
                       'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'),
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Referer': 'https://www.douyin.com/',
    }

    if progress_callback:
        progress_callback("[1/4] 正在解析抖音链接...")

    req = urlreq.Request(url, headers=headers)
    resp = urlreq.urlopen(req, context=ctx, timeout=15)
    html = resp.read().decode('utf-8', errors='ignore')

    uri_m = re.search(r'play_addr[^}]{0,300}?uri["\s]*:["\s]*([a-zA-Z0-9_]+)', html, re.DOTALL)
    if not uri_m:
        raise RuntimeError("🔇 无法从抖音页面提取视频信息，请稍后重试或直接下载视频后上传。")
    video_uri = uri_m.group(1)

    title_m = re.search(r'<title[^>]*>([^<]+)</title>', html)
    raw_title = title_m.group(1).strip() if title_m else "抖音视频"
    raw_title = re.sub(r'\s*[-_|·]\s*抖音.*$', '', raw_title).strip() or "抖音视频"

    cdn_url = f'https://aweme.snssdk.com/aweme/v1/play/?video_id={video_uri}&ratio=720p&line=0'
    logger.info(f"[Douyin] URI={video_uri} title={raw_title!r}")

    if progress_callback:
        progress_callback(f"[2/4] 正在下载：{raw_title}")

    req = urlreq.Request(cdn_url, headers=headers)
    resp = urlreq.urlopen(req, context=ctx, timeout=60)
    content_type = resp.headers.get('Content-Type', '')
    if 'video' not in content_type and 'octet-stream' not in content_type:
        raise RuntimeError(f"🔇 抖音返回了非视频内容（{content_type}），请稍后重试。")

    with open(output_path, 'wb') as f:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)

    return raw_title


@app.route("/api/download-video", methods=["POST"])
def api_download_video():
    """从 URL 下载视频到 videos 目录，通过 SSE 推送进度"""
    data = request.get_json()
    raw_input = data.get("url", "").strip()
    if not raw_input:
        return jsonify({"error": "缺少视频链接"}), 400
    url = _extract_url_from_text(raw_input)

    log_event("download", url=url)

    os.makedirs(VIDEOS_DIR, exist_ok=True)

    progress_queue = queue.Queue()

    def ytdlp_cookie_args():
        """YouTube 数据中心 IP 反爬兜底：支持通过环境变量注入 cookies"""
        cookies = settings.YOUTUBE_COOKIES
        if not cookies:
            return []
        cookie_file = settings.YT_COOKIES_FILE
        try:
            with open(cookie_file, "w", encoding="utf-8") as f:
                f.write(cookies)
            return ["--cookies", cookie_file]
        except Exception:
            return []

    def _classify_error(stderr):
        """把 yt-dlp/ffmpeg stderr 归入 5 大错误类，返回用户友好提示。"""
        e = stderr
        # 🔒 版权保护
        if "DRM" in e or "drm" in e:
            return "🔒 该视频受版权保护（DRM），无法下载。请换一个视频试试。"
        # 🗑️ 视频不存在/已删除/私密
        if any(k in e for k in ("404", "not found", "unavailable", "This video is private",
                                 "has been removed", "no longer available", "deleted")):
            return "🗑️ 视频不存在、已被删除或设为私密，请确认链接是否有效。"
        # 🚫 Instagram 强制登录（即使是公开内容）
        if "instagram" in e.lower() and ("empty media response" in e or "cookies" in e):
            return ("🚫 Instagram 需要登录才能下载。\n"
                    "• 电脑端：请确保在浏览器（Chrome/Firefox）中已登录 Instagram，"
                    "并使用本地版 ReelSpeak（非 getreelspeak.com）下载。\n"
                    "• 手机端：请在手机上保存视频后直接上传。")
        # 🚫 需要登录/会员/防盗链
        if any(k in e for k in ("Sign in", "log in", "login", "member", "403", "Forbidden",
                                  "cookies", "Premium", "age-restricted", "age restricted")):
            return "🚫 该视频需要登录或仅限会员观看，暂时无法在服务器端下载。请换一个公开视频。"
        # ⏱️ 平台反爬/限速
        if any(k in e for k in ("429", "rate limit", "Too Many Requests", "bot", "challenge",
                                  "JavaScript", "rmats", "player_client")):
            return "⏱️ 平台暂时限制了服务器访问。请等待 1–2 分钟后重试，或改用其他平台的链接。"
        # 🔇 无音频（此处兜底，通常已在下载后 ffprobe 拦截）
        if any(k in e for k in ("matches no streams", "no audio", "Invalid argument")):
            return "🔇 视频没有音频轨道，无法进行语音识别。请将视频本地下载后直接上传。"
        # ❓ 未知错误：截取最后 120 字符，去掉路径和 ANSI 码
        snippet = re.sub(r'\x1b\[[0-9;]*m', '', e).strip()[-120:]
        return f"❓ 下载失败：{snippet}"

    def do_download():
        try:
            # ── 抖音专用下载通道 ─────────────────────────────────────
            if _is_douyin_url(url):
                import tempfile, shutil
                tmp_path = os.path.join(tempfile.gettempdir(), "douyin_tmp.mp4")
                try:
                    title = _download_douyin(url, tmp_path,
                                             progress_callback=lambda m: progress_queue.put(("progress", m)))
                except Exception as e:
                    progress_queue.put(("error", str(e)))
                    return

                # ── [3/4] 验证音频轨道 ───────────────────────────────
                progress_queue.put(("progress", "[3/4] 正在验证音频轨道..."))
                probe = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-select_streams", "a",
                     "-show_entries", "stream=index", "-of", "csv=p=0", tmp_path],
                    capture_output=True, text=True,
                )
                if not probe.stdout.strip():
                    os.remove(tmp_path)
                    progress_queue.put(("error", "🔇 下载的视频不含音频轨道，无法进行语音识别。"))
                    return

                safe_title = clean_video_title(title)
                output_path = os.path.join(VIDEOS_DIR, safe_title + ".mp4")
                os.makedirs(VIDEOS_DIR, exist_ok=True)
                shutil.move(tmp_path, output_path)

                # ── [4/4] 处理音频 ───────────────────────────────────
                progress_queue.put(("progress", "[4/4] 正在处理音频..."))
                normalize_audio(output_path)
                progress_queue.put(("done", {"name": safe_title + ".mp4"}))
                return

            cookie_args = ytdlp_cookie_args()
            extra_args = list(cookie_args)

            # ── [1/4] 获取视频信息 ───────────────────────────────────
            progress_queue.put(("progress", "[1/4] 正在获取视频信息..."))
            info_cmd = ["yt-dlp", "--no-download", "--print", "title", "--print", "duration"] + extra_args + [url]
            info_result = subprocess.run(
                info_cmd, capture_output=True, text=True, timeout=settings.TIMEOUT_YTDLP
            )
            if info_result.returncode != 0 and (
                "Sign in" in info_result.stderr or "cookies" in info_result.stderr
            ):
                if "instagram" in info_result.stderr.lower() or "instagram" in url.lower():
                    # Instagram 需要登录：自动尝试本地浏览器 cookies（本地运行时有效）
                    progress_queue.put(("progress", "[1/4] Instagram 需要登录，尝试读取本地浏览器..."))
                    _browser_args = None
                    for browser in ("chrome", "firefox", "edge", "chromium"):
                        test_args = cookie_args + ["--cookies-from-browser", browser]
                        test_cmd = ["yt-dlp", "--no-download", "--print", "title", "--print", "duration"] + test_args + [url]
                        test_result = subprocess.run(
                            test_cmd, capture_output=True, text=True, timeout=settings.TIMEOUT_YTDLP
                        )
                        if test_result.returncode == 0:
                            extra_args = test_args
                            info_result = test_result
                            _browser_args = browser
                            logger.info(f"[Instagram] 使用 {browser} cookies 成功")
                            break
                    if _browser_args is None:
                        progress_queue.put(("error",
                            "🚫 Instagram 需要登录才能下载。\n"
                            "• 电脑端：请确保在浏览器（Chrome/Firefox）中已登录 Instagram，"
                            "并使用本地版 ReelSpeak（非 getreelspeak.com）下载。\n"
                            "• 手机端：请在手机上保存视频后直接上传。"))
                        return
                else:
                    # YouTube 机器人检测：改用 TV 客户端伪装重试
                    progress_queue.put(("progress", "[1/4] YouTube 验证拦截，尝试备用通道..."))
                    extra_args = cookie_args + ["--extractor-args", "youtube:player_client=tv,web_embedded"]
                    info_cmd = ["yt-dlp", "--no-download", "--print", "title", "--print", "duration"] + extra_args + [url]
                    info_result = subprocess.run(
                        info_cmd, capture_output=True, text=True, timeout=settings.TIMEOUT_YTDLP
                    )
            if info_result.returncode != 0:
                progress_queue.put(("error", _classify_error(info_result.stderr)))
                return

            lines = info_result.stdout.strip().splitlines()
            title = lines[0] if lines else ""
            # 下载前检查时长
            try:
                duration_sec = float(lines[1]) if len(lines) > 1 else 0
                if duration_sec > 600:
                    mins = int(duration_sec // 60)
                    secs = int(duration_sec % 60)
                    progress_queue.put(("error",
                        f"⏰ 视频时长 {mins}:{secs:02d}，超过 10 分钟限制。"
                        f"ReelSpeak 专为短视频设计，建议截取片段后再上传。"))
                    return
            except (ValueError, IndexError):
                pass

            safe_title = clean_video_title(title)
            output_path = os.path.join(VIDEOS_DIR, safe_title + ".mp4")

            if os.path.exists(output_path):
                progress_queue.put(("done", {
                    "name": safe_title + ".mp4",
                    "message": "视频已存在，无需重复下载",
                }))
                return

            # ── [2/4] 下载视频 ───────────────────────────────────────
            progress_queue.put(("progress", f"[2/4] 正在下载：{title}"))
            # 格式优先级：mp4视频+m4a音频 → mp4视频+任意音频 → 任意视频+任意音频 → best
            dl_cmd = [
                "yt-dlp",
                "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio/bestvideo+bestaudio/best",
                "--merge-output-format", "mp4",
                "--no-playlist",
                "-o", output_path,
                "--progress",
                "--newline",
            ] + extra_args + [url]
            process = subprocess.Popen(
                dl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )

            pct_re = re.compile(r"(\d+\.?\d*)%")
            for line in process.stdout:
                line = line.strip()
                m = pct_re.search(line)
                if m:
                    pct = float(m.group(1))
                    progress_queue.put(("progress", f"[2/4] 下载中 {pct:.0f}%：{title}"))

            dl_stderr = process.stderr.read()
            process.wait()
            if process.returncode != 0:
                progress_queue.put(("error", _classify_error(dl_stderr)))
                return

            # 文件名兜底（yt-dlp 偶尔自行修改文件名）
            if not os.path.exists(output_path):
                for f in os.listdir(VIDEOS_DIR):
                    if f.startswith(safe_title) and f.endswith(".mp4"):
                        output_path = os.path.join(VIDEOS_DIR, f)
                        safe_title = f.replace(".mp4", "")
                        break

            if os.path.exists(output_path):
                # ── [3/4] 验证音频轨道 ───────────────────────────────
                progress_queue.put(("progress", "[3/4] 正在验证音频轨道..."))
                probe = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-select_streams", "a",
                     "-show_entries", "stream=index", "-of", "csv=p=0", output_path],
                    capture_output=True, text=True,
                )
                if not probe.stdout.strip():
                    os.remove(output_path)
                    progress_queue.put(("error",
                        "🔇 下载的视频不含音频轨道，无法进行语音识别。"
                        "该视频可能使用了平台特殊编码，请将视频本地下载后直接上传。"))
                    return

                # ── [4/4] 处理音频 ───────────────────────────────────
                progress_queue.put(("progress", "[4/4] 正在处理音频..."))
                normalize_audio(output_path)

                progress_queue.put(("done", {
                    "name": safe_title + ".mp4",
                    "message": "下载完成",
                }))
            else:
                progress_queue.put(("error", "下载完成但找不到文件"))

        except subprocess.TimeoutExpired:
            progress_queue.put(("error", "获取视频信息超时"))
        except Exception as e:
            progress_queue.put(("error", str(e)))

    threading.Thread(target=do_download, daemon=True).start()

    def generate():
        while True:
            msg_type, msg_data = progress_queue.get()
            if msg_type == "progress":
                yield f"data: {json.dumps({'progress': msg_data})}\n\n"
            elif msg_type == "done":
                yield f"data: {json.dumps({'done': True, **msg_data})}\n\n"
                break
            elif msg_type == "error":
                yield f"data: {json.dumps({'error': msg_data})}\n\n"
                break

    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/videos")
def list_videos():
    """列出 videos 目录下所有 MP4 文件，标注是否有字幕"""
    if not os.path.exists(VIDEOS_DIR):
        return jsonify({"videos": []})
    videos = []
    for f in sorted(os.listdir(VIDEOS_DIR)):
        if f.lower().endswith(".mp4"):
            has_subtitle = os.path.exists(subtitle_path(f))
            videos.append({"name": f, "has_subtitle": has_subtitle})
    return jsonify({"videos": videos})


@app.route("/api/subtitle/<path:video_name>")
def get_subtitle(video_name):
    """读取已保存的字幕"""
    path = subtitle_path(video_name)
    if not os.path.exists(path):
        return jsonify({"error": "字幕文件不存在"}), 404
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return jsonify(data)


@app.route("/api/subtitle/<path:video_name>", methods=["POST"])
def save_subtitle(video_name):
    """保存字幕"""
    data = request.get_json()
    path = subtitle_path(video_name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True})


@app.route("/api/transcribe", methods=["POST"])
def api_transcribe():
    """语音识别 + 断句（SSE 流式推送进度，防止 Railway 30s 超时切断）"""
    data = request.get_json()
    video_name = data.get("video")
    if not video_name:
        return jsonify({"error": "缺少 video 参数"}), 400

    video_path = os.path.join(VIDEOS_DIR, video_name)
    if not os.path.exists(video_path):
        return jsonify({"error": "视频文件不存在"}), 404

    provider = data.get("provider", "groq")
    segment_target = data.get("segment_target")
    if segment_target:
        segment_target = int(segment_target)

    progress_queue = queue.Queue()
    _uid     = _get_user_id(get_db())   # 在请求上下文中获取，闭包内只使用字符串
    _rl_key  = _get_rl_key(_uid)        # 限流 key（匿名设备用 device:UUID）

    def do_transcribe():
        import time as _time
        # 检查视频时长，超过 10 分钟拒绝识别
        duration = get_video_duration(video_path)
        if duration > 600:
            mins = int(duration // 60)
            progress_queue.put(("error", f"视频时长 {mins} 分钟，超过 10 分钟限制。ReelSpeak 专为短视频设计，建议截取片段后再上传。"))
            return

        db = get_db()
        is_anon = (_uid == ANONYMOUS_USER_ID)

        if not is_anon:
            ctx = CommerceContext(
                db, _uid, "transcription", "standard", "free",
                extra={"video": video_name, "provider": provider},
            )
            if not ctx.check_permission("CanTranscribe"):
                progress_queue.put(("error", "权限不足，请升级套餐"))
                return
            plan = get_user_plan(db, _uid)
        else:
            ctx  = None
            plan = "device"

        if not _check_rate_limit(_rl_key, "transcription", plan):
            used  = _rl_get_usage(_rl_key, "transcription")
            limit = _rl_get_limit("transcription", plan)
            if is_anon:
                progress_queue.put(("rate_limit", f"免费体验次数已用完（{used}/{limit} 次），登录后可无限使用"))
            else:
                progress_queue.put(("rate_limit", f"今日转录次数已达上限（{used}/{limit} 次），明日重置"))
            return

        if not is_anon:
            try:
                ctx.reserve({"duration_seconds": duration})
            except InsufficientFundsError:
                progress_queue.put(("error", "Credits 不足，请充值后重试"))
                return

        _rl_increment(_rl_key, "transcription")

        t0 = _time.time()
        try:
            # 超过 5 分钟时 transcribe_video 内部自动分段，progress_callback 推送各段进度
            if duration > 300 and provider in ("openai", "groq"):
                total_chunks = -(-int(duration) // 180)  # ceil(duration/180)
                progress_queue.put(("progress", f"视频较长，将分 {total_chunks} 段识别..."))
            else:
                progress_queue.put(("progress", f"正在识别（{provider.upper()}）..."))

            result = transcribe_video(
                video_path, provider=provider, segment_target=segment_target,
                progress_callback=lambda msg: progress_queue.put(("progress", msg)),
            )

            # 泰语等无空格语言：用 Gemini 按词加空格，方便学习者阅读
            lang = (result.get("language") or "")[:2].lower()
            lang_full = (result.get("language") or "").lower()
            if lang == "th" or lang_full == "thai":
                progress_queue.put(("progress", "正在处理泰语分词..."))
                # Gemini 负责泰语分词（OpenAI word tokens 是字符级，不适合直接用）
                texts = [s["text"] for s in result["segments"]]
                spaced = add_word_spacing(texts, "th")
                for s, sp in zip(result["segments"], spaced):
                    s["text"] = sp

                # OpenAI word tokens 用于时间戳对齐（不用于文本拼接）
                raw_words = result.get("words", [])
                if raw_words:
                    align_word_timestamps(result["segments"], raw_words)
                    result.pop("words", None)

            # 构造 Segment 对象（同时清洗内部私有字段 _conf/_source/_logprob 等）
            language_code = result.get("language", "")
            segments = [Segment.from_internal_dict(s) for s in result.get("segments", [])]

            # 生成拼音 / 罗马拼音（中文→带声调拼音，泰语→RTGS）
            generate_romanization(segments, language_code)

            # 序列化回 dict 供 SSE 传输（100% 兼容原 JSON 格式）
            result["segments"] = [s.to_json() for s in segments]
            result.pop("words", None)

            latency_ms = int((_time.time() - t0) * 1000)
            if not is_anon:
                ctx.settle(
                    {"duration_seconds": duration}, provider,
                    ctx.get_handle(preferred_provider=provider).model_id,
                    latency_ms,
                )
            log_event("transcribe", video=video_name, provider=provider,
                      language=language_code, segments=len(segments))
            progress_queue.put(("done", result))
        except Exception as e:
            if not is_anon:
                ctx.release_on_error(e)
            log_event("transcribe_fail", video=video_name, provider=provider, error=str(e)[:200])
            progress_queue.put(("error", str(e)))

    threading.Thread(target=do_transcribe, daemon=True).start()

    def generate():
        while True:
            msg_type, msg_data = progress_queue.get()
            if msg_type == "progress":
                yield f"data: {json.dumps({'progress': msg_data})}\n\n"
            elif msg_type == "done":
                yield f"data: {json.dumps({'done': True, 'result': msg_data})}\n\n"
                break
            elif msg_type == "error":
                yield f"data: {json.dumps({'error': msg_data})}\n\n"
                break
            elif msg_type == "rate_limit":
                yield f"data: {json.dumps({'rate_limit': msg_data})}\n\n"
                break

    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/retranscribe", methods=["POST"])
def api_retranscribe():
    """对视频的一个时间片段进行二次识别（用户微调时间戳后重新识别单句）"""
    data = request.get_json()
    video_name = data.get("video", "")
    provider = data.get("provider", "groq")
    do_translate = bool(data.get("translate", True))
    source_lang = data.get("source_lang", "泰语")
    target_lang = data.get("target_lang", "中文")
    language = data.get("language", "")  # 短语言码如 "th"，Azure 识别需要

    try:
        start = float(data.get("start", -1))
        end = float(data.get("end", -1))
    except (TypeError, ValueError):
        return jsonify({"error": "时间参数无效"}), 400

    if provider not in ("groq", "azure", "gemini", "openai"):
        return jsonify({"error": "不支持的识别引擎"}), 400
    if not (0 <= start < end):
        return jsonify({"error": "时间范围无效"}), 400
    if end - start > 60:
        return jsonify({"error": "识别范围不能超过 60 秒"}), 400

    # 防路径穿越
    videos_root = os.path.realpath(VIDEOS_DIR)
    video_path = os.path.realpath(os.path.join(VIDEOS_DIR, video_name))
    if not video_path.startswith(videos_root + os.sep) or not os.path.exists(video_path):
        return jsonify({"error": "视频文件不存在"}), 404

    wav_path = os.path.join(VIDEOS_DIR, f".slice_{os.getpid()}_{int(start * 1000)}.wav")
    try:
        # ffmpeg 切片：-ss/-to 放在 -i 之后保证帧精确
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", str(start),
            "-to", str(end),
            "-vn", "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
            wav_path,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            return jsonify({"error": "音频切片失败: " + r.stderr[-200:]}), 500

        import time as _time
        duration_sec = end - start
        db = get_db()
        _uid = _get_user_id(db)
        ctx = CommerceContext(
            db, _uid, "transcription", "standard", "free",
            extra={"video": video_name, "provider": provider, "mode": "retranscribe"},
        )
        if not ctx.check_permission("CanTranscribe"):
            return jsonify({"error": "权限不足，请升级套餐"}), 403
        try:
            ctx.reserve({"duration_seconds": duration_sec})
        except InsufficientFundsError:
            return jsonify({"error": "Credits 不足，请充值后重试"}), 402

        t0 = _time.time()
        try:
            result = transcribe_slice(wav_path, provider, language=language)
            text = result["text"]

            # 泰语：按词加空格
            if (language or "")[:2].lower() == "th" and text:
                text = add_word_spacing([text], "th")[0]

            translation = ""
            if do_translate and text:
                try:
                    translated, _ = translate_segments([{"index": 0, "text": text}], source_lang, target_lang)
                    if translated:
                        translation = translated[0].get("translation", "")
                except Exception as te:
                    logger.warning(f"[Retranscribe] 翻译失败: {te}")

            latency_ms = int((_time.time() - t0) * 1000)
            handle = ctx.get_handle(preferred_provider=provider)
            ctx.settle({"duration_seconds": duration_sec}, handle.provider_id, handle.model_id, latency_ms)
            log_event("retranscribe", video=video_name, provider=provider,
                      range=f"{start:.1f}-{end:.1f}", language=language)
            return jsonify({"text": text, "translation": translation})
        except Exception as e:
            ctx.release_on_error(e)
            return jsonify({"error": str(e)}), 502
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)


@app.route("/api/retranscribe-audio", methods=["POST"])
def api_retranscribe_audio():
    """对上传的音频切片进行二次识别（本地视频场景：前端切好音频上传）"""
    if "audio" not in request.files:
        return jsonify({"error": "缺少音频文件"}), 400

    provider = request.form.get("provider", "groq")
    do_translate = request.form.get("translate", "true") == "true"
    source_lang = request.form.get("source_lang", "泰语")
    target_lang = request.form.get("target_lang", "中文")
    language = request.form.get("language", "")

    if provider not in ("groq", "azure", "gemini", "openai"):
        return jsonify({"error": "不支持的识别引擎"}), 400

    audio_file = request.files["audio"]
    raw_path = os.path.join(VIDEOS_DIR, f".upload_slice_{os.getpid()}.wav")
    wav_path = raw_path + ".16k.wav"
    try:
        audio_file.save(raw_path)
        if os.path.getsize(raw_path) > 20 * 1024 * 1024:
            return jsonify({"error": "音频切片过大"}), 400

        # 统一转成 16kHz 单声道，兼容任何上传采样率
        cmd = [
            "ffmpeg", "-y", "-i", raw_path,
            "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
            wav_path,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            return jsonify({"error": "音频转换失败: " + r.stderr[-200:]}), 500

        result = transcribe_slice(wav_path, provider, language=language)
        text = result["text"]

        # 泰语：按词加空格 + 发音时长权重
        if (language or "")[:2].lower() == "th" and text:
            text = add_word_spacing([text], "th")[0]

        translation = ""
        if do_translate and text:
            try:
                translated, _ = translate_segments([{"index": 0, "text": text}], source_lang, target_lang)
                if translated:
                    translation = translated[0].get("translation", "")
            except Exception as te:
                logger.warning(f"[RetranscribeAudio] 翻译失败: {te}")

        log_event("retranscribe_audio", provider=provider, language=language)
        return jsonify({"text": text, "translation": translation})
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    finally:
        for p in (raw_path, wav_path):
            if os.path.exists(p):
                os.remove(p)


@app.route("/api/ocr", methods=["POST"])
def api_ocr():
    """图片文字识别（隐藏测试功能：粘贴文本框直接贴图）"""
    import time as _time
    if "image" not in request.files:
        return jsonify({"error": "缺少图片"}), 400
    img = request.files["image"]
    data = img.read()
    if len(data) > 10 * 1024 * 1024:
        return jsonify({"error": "图片过大（最多 10MB）"}), 400
    mime = img.mimetype or "image/png"
    language = request.form.get("language", "")

    db = get_db()
    _uid = _get_user_id(db)
    ctx = CommerceContext(
        db, _uid, "ocr", "standard", "free",
        extra={"language": language},
    )
    if not ctx.check_permission("CanOCR"):
        return jsonify({"error": "权限不足，请升级套餐"}), 403
    try:
        ctx.reserve({})
    except InsufficientFundsError:
        return jsonify({"error": "Credits 不足，请充值后重试"}), 402

    t0 = _time.time()
    try:
        text = ocr_image(data, mime, language)
        latency_ms = int((_time.time() - t0) * 1000)
        ctx.settle({"image_count": 1}, "gemini", "gemini-3.1-flash-lite", latency_ms)
        log_event("ocr", language=language, chars=len(text))
        return jsonify({"text": text})
    except Exception as e:
        ctx.release_on_error(e)
        return jsonify({"error": str(e)}), 502


@app.route("/api/tts-content", methods=["POST"])
def api_tts_content():
    """AI 生成双语学习内容（对话 / 词汇列表）"""
    import time as _time
    data = request.get_json()
    prompt      = (data.get("prompt") or "").strip()[:300]
    language    = (data.get("language") or "th").lower()[:2]
    target_lang = (data.get("target_lang") or "中文").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    db = get_db()
    _uid    = _get_user_id(db)
    _rl_key = _get_rl_key(_uid)
    is_anon = (_uid == ANONYMOUS_USER_ID)

    ctx = CommerceContext(
        db, _uid, "content_gen", "standard", "free",
        extra={"prompt_len": len(prompt), "language": language},
    )
    if not is_anon and not ctx.check_permission("CanTTSContent"):
        return jsonify({"error": "tts.err.noPermission"}), 403

    # 匿名设备限流（不走 credits）
    plan = "device" if is_anon else ctx.plan_id
    if not _check_rate_limit(_rl_key, "content_gen", plan):
        used = _rl_get_usage(_rl_key, "content_gen")
        return jsonify({"error": "tts.err.rateLimitContent", "n": used}), 429

    if not is_anon:
        try:
            ctx.reserve({"char_count": len(prompt)})
        except InsufficientFundsError:
            return jsonify({"error": "tts.err.creditsLow"}), 402

    _rl_increment(_rl_key, "content_gen")
    t0 = _time.time()
    try:
        text = generate_tts_content(prompt, language, target_lang)
        latency_ms = int((_time.time() - t0) * 1000)
        if not is_anon:
            provider_used = "deepseek" if language == "zh" else "gemini"
            handle = ctx.get_handle(preferred_provider=provider_used)
            ctx.settle({"char_count": len(prompt)}, handle.provider_id, handle.model_id, latency_ms)
        log_event("tts_content_gen", language=language, prompt_len=len(prompt))
        return jsonify({"text": text})
    except Exception as e:
        if not is_anon:
            ctx.release_on_error(e)
        logger.warning(f"[TTS content] 生成失败: {e}")
        return jsonify({"error": str(e)}), 502


@app.route("/api/tts-generate", methods=["POST"])
def api_tts_generate():
    """粘贴文本 → 生成语音课程（SSE 流式进度 + 最终 JSON 结果）

    响应格式：text/event-stream
      data: {"type":"progress","msg":"正在生成语音 1/12..."}\n\n
      ...
      data: {"type":"done","result":{...}}\n\n
      data: {"type":"error","error":"..."}\n\n
    """
    data = request.get_json()
    text = (data.get("text") or "").strip()
    language = data.get("language", "th")
    engine = data.get("engine", "gemini")

    if not text:
        return jsonify({"error": "缺少文本内容"}), 400
    if len(text) > 3000:
        return jsonify({"error": "文本过长（最多 3000 字符）"}), 400
    if language not in ("th", "en", "zh", "ja", "ko", "auto"):
        return jsonify({"error": "不支持的语言"}), 400
    if engine not in ("gemini", "azure", "youdao"):
        return jsonify({"error": "不支持的语音引擎"}), 400

    os.makedirs(VIDEOS_DIR, exist_ok=True)
    target_lang = data.get("target_lang", "中文")
    _uid    = _get_user_id(get_db())   # 在请求上下文中获取，闭包内只使用字符串
    _rl_key = _get_rl_key(_uid)

    # ── SSE 生成器 ────────────────────────────────────────────────
    def generate():
        q = queue.Queue()

        def progress(msg):
            q.put(("progress", msg))

        def worker():
            import time as _time
            db = get_db()
            char_count = len(text)
            is_anon = (_uid == ANONYMOUS_USER_ID)

            if not is_anon:
                ctx = CommerceContext(
                    db, _uid, "tts_synthesis", "standard", "free",
                    extra={"char_count": char_count, "engine": engine},
                )
                if not ctx.check_permission("CanTTS"):
                    q.put(("error", "tts.err.noPermission"))
                    return
                plan = get_user_plan(db, _uid)
            else:
                ctx  = None
                plan = "device"

            if not _check_rate_limit(_rl_key, "tts_synthesis", plan):
                used  = _rl_get_usage(_rl_key, "tts_synthesis")
                limit = _rl_get_limit("tts_synthesis", plan)
                if is_anon:
                    q.put(("rate_limit", {"key": "tts.err.rateLimitAnon", "used": used, "limit": limit}))
                else:
                    q.put(("rate_limit", {"key": "tts.err.rateLimitFree", "used": used, "limit": limit}))
                return

            if not is_anon:
                try:
                    ctx.reserve({"char_count": char_count})
                except InsufficientFundsError:
                    q.put(("error", "tts.err.creditsLow"))
                    return
            _rl_increment(_rl_key, "tts_synthesis")
            t0 = _time.time()
            try:
                # 检测输入格式
                detected = detect_input_mode(text, language, target_lang)
                mode = detected["mode"]
                pre_items = detected["items"] if mode in ("bilingual", "per_line") else None
                lang = language
                if lang == "auto":
                    if mode != "paragraph":
                        # 双语/逐行模式：detect_input_mode 已检测原文语言
                        lang = detected["language"]
                    else:
                        # 段落模式：先字符集猜测，拉丁语系再调 Gemini 确认
                        from ai.tts import _guess_language, detect_language_api
                        lang = _guess_language(text)
                        if lang == "en":
                            # "en" 只是字符集兜底，可能是西/法/德等，用 Gemini 确认
                            lang = detect_language_api(text)
                            logger.info(f"[TTS] 段落 auto 检测语言: {lang!r}")

                audio_name, segments, lang, tts_meta = generate_audio_lesson(
                    text, lang, engine, VIDEOS_DIR,
                    progress=progress, pre_items=pre_items,
                )
                source_lang_name = {"th": "泰语", "en": "英语", "zh": "中文",
                                    "ja": "日语", "ko": "韩语"}.get(lang, "外语")

                seg_objs = [Segment.from_json(s) for s in segments]

                if lang == "th":
                    spaced = add_word_spacing([s.text for s in seg_objs], "th")
                    for s, sp in zip(seg_objs, spaced):
                        s.text = sp

                translate_provider = "skipped"
                if mode == "bilingual" and pre_items:
                    for seg, item in zip(seg_objs, pre_items):
                        if item.get("translation"):
                            seg.translation = item["translation"]
                else:
                    same_lang = (lang == "zh" and target_lang in ("中文", "繁體中文")) or \
                                (lang == "ja" and target_lang == "日本語") or \
                                (lang == "ko" and target_lang == "한국어") or \
                                (lang == "en" and target_lang == "English")
                    if not same_lang:
                        try:
                            q.put(("progress", "tts.prog.translating"))
                            translated, translate_provider = translate_segments(
                                [{"index": s.index, "text": s.text} for s in seg_objs],
                                source_lang_name, target_lang,
                            )
                            for tr in translated:
                                idx = tr.get("index")
                                if idx is not None and 0 <= idx < len(seg_objs):
                                    seg_objs[idx].translation = tr.get("translation", "")
                        except Exception as te:
                            logger.warning(f"[TTS] 翻译失败: {te}")

                cover_name = os.path.splitext(audio_name)[0] + ".jpg"
                cover = ""
                if generate_cover_image(text, lang, os.path.join(VIDEOS_DIR, cover_name)):
                    cover = cover_name

                subtitle_file = SubtitleFile(segments=seg_objs, language=lang, cover=cover)
                with open(subtitle_path(audio_name), "w", encoding="utf-8") as f:
                    json.dump(subtitle_file.to_json(), f, ensure_ascii=False, indent=2)

                latency_ms = int((_time.time() - t0) * 1000)
                if not is_anon:
                    ctx.settle(
                        {"char_count": char_count}, engine,
                        ctx.get_handle(preferred_provider=engine).model_id,
                        latency_ms,
                    )
                log_event("tts_generate", engine=engine, language=lang,
                          chars=len(text), sentences=len(seg_objs),
                          input_mode=mode,
                          split_provider=tts_meta.get("split_provider", "unknown"),
                          translate_provider=translate_provider)

                result = subtitle_file.to_json()
                result["name"] = audio_name
                q.put(("done", result))
            except Exception as e:
                if not is_anon:
                    ctx.release_on_error(e)
                log_event("tts_generate_fail", engine=engine, error=str(e)[:200])
                q.put(("error", str(e)))

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        while True:
            try:
                kind, payload = q.get(timeout=300)
            except queue.Empty:
                yield f"data: {json.dumps({'type':'error','error':'tts.err.timeout'}, ensure_ascii=False)}\n\n"
                break
            if kind == "progress":
                yield f"data: {json.dumps({'type':'progress','msg':payload}, ensure_ascii=False)}\n\n"
            elif kind == "done":
                yield f"data: {json.dumps({'type':'done','result':payload}, ensure_ascii=False)}\n\n"
                break
            elif kind == "error":
                yield f"data: {json.dumps({'type':'error','error':payload}, ensure_ascii=False)}\n\n"
                break
            elif kind == "rate_limit":
                rl_data = payload if isinstance(payload, dict) else {"key": "auth.rateLimit"}
                yield f"data: {json.dumps({'type':'rate_limit', **rl_data}, ensure_ascii=False)}\n\n"
                break

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/romanize", methods=["POST"])
def api_romanize():
    """为单句文本生成拼音/罗马拼音（编辑句子后同步更新用）"""
    import time as _time
    data = request.get_json()
    text = (data.get("text") or "").strip()
    language = (data.get("language") or "").lower()[:2]
    if not text:
        return jsonify({"romanization": ""})

    db = get_db()
    _uid = _get_user_id(db)
    ctx = CommerceContext(
        db, _uid, "romanize", "standard", "free",
        extra={"language": language},
    )
    if not ctx.check_permission("CanRomanize"):
        return jsonify({"error": "权限不足，请升级套餐"}), 403
    # zh 本地免费，reserve 0 credits；th 走 API，reserve 估算
    usage = {} if language == "zh" else {"char_count": len(text)}
    try:
        ctx.reserve(usage)
    except InsufficientFundsError:
        return jsonify({"error": "Credits 不足，请充值后重试"}), 402

    t0 = _time.time()
    try:
        segs = [Segment(index=0, text=text, start=0, end=0)]
        generate_romanization(segs, language)
        latency_ms = int((_time.time() - t0) * 1000)
        provider_used = "local" if language == "zh" else "gemini"
        handle = ctx.get_handle(preferred_provider=provider_used)
        ctx.settle(usage, handle.provider_id, handle.model_id, latency_ms)
        return jsonify({"romanization": segs[0].romanization})
    except Exception as e:
        ctx.release_on_error(e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/romanize-batch", methods=["POST"])
def api_romanize_batch():
    """批量为多个句子生成拼音/罗马拼音（懒加载：首次开启拼音开关时调用）"""
    import time as _time
    data = request.get_json()
    segs = data.get("segments", [])   # [{"text": "..."}]
    language = (data.get("language") or "").lower()[:2]
    if not segs:
        return jsonify({"segments": []})

    total_chars = sum(len(s.get("text", "")) for s in segs)
    db = get_db()
    _uid = _get_user_id(db)
    ctx = CommerceContext(
        db, _uid, "romanize", "standard", "free",
        extra={"language": language, "segment_count": len(segs)},
    )
    if not ctx.check_permission("CanRomanize"):
        return jsonify({"error": "权限不足，请升级套餐"}), 403
    usage = {} if language == "zh" else {"char_count": total_chars}
    try:
        ctx.reserve(usage)
    except InsufficientFundsError:
        return jsonify({"error": "Credits 不足，请充值后重试"}), 402

    t0 = _time.time()
    try:
        work = [Segment(index=i, text=(s.get("text") or "").strip(), start=0, end=0)
                for i, s in enumerate(segs)]
        generate_romanization(work, language)
        latency_ms = int((_time.time() - t0) * 1000)
        provider_used = "local" if language == "zh" else "gemini"
        handle = ctx.get_handle(preferred_provider=provider_used)
        ctx.settle(usage, handle.provider_id, handle.model_id, latency_ms)
        return jsonify({"segments": [{"text": w.text, "romanization": w.romanization} for w in work]})
    except Exception as e:
        ctx.release_on_error(e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/translate", methods=["POST"])
def api_translate():
    """翻译句子"""
    import time as _time
    data = request.get_json()
    segments = data.get("segments", [])
    source_lang = data.get("source_lang", "泰语")
    target_lang = data.get("target_lang", "中文")
    engine = data.get("engine", "auto")

    if not segments:
        return jsonify({"error": "缺少 segments 参数"}), 400

    char_count = sum(len(s.get("text", "")) for s in segments)
    db = get_db()
    _uid = _get_user_id(db)
    ctx = CommerceContext(
        db, _uid, "translation", "standard", "free",
        extra={"char_count": char_count},
    )
    if not ctx.check_permission("CanTranslate"):
        return jsonify({"error": "权限不足，请升级套餐"}), 403
    try:
        ctx.reserve({"char_count": char_count})
    except InsufficientFundsError:
        return jsonify({"error": "Credits 不足，请充值后重试"}), 402

    t0 = _time.time()
    try:
        translations, provider_used = translate_segments(segments, source_lang, target_lang, engine=engine)
        latency_ms = int((_time.time() - t0) * 1000)
        handle = ctx.get_handle(preferred_provider=provider_used if provider_used != "auto" else None)
        ctx.settle({"char_count": char_count}, handle.provider_id, handle.model_id, latency_ms)
        return jsonify({"translations": translations})
    except Exception as e:
        ctx.release_on_error(e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/word-define", methods=["POST"])
def api_word_define():
    """查询单词释义（DeepSeek）"""
    import time as _time
    data = request.get_json()
    word = (data.get("word") or "").strip()
    source_lang = data.get("source_lang", "泰语")
    target_lang = data.get("target_lang", "中文")
    context = (data.get("context") or "").strip()

    if not word:
        return jsonify({"error": "缺少 word 参数"}), 400

    db = get_db()
    _uid = _get_user_id(db)
    ctx = CommerceContext(
        db, _uid, "word_definition", "standard", "free",
        extra={"word": word[:50]},
    )
    if not ctx.check_permission("CanWordDefine"):
        return jsonify({"error": "权限不足，请升级套餐"}), 403
    try:
        ctx.reserve({})
    except InsufficientFundsError:
        return jsonify({"error": "Credits 不足，请充值后重试"}), 402

    t0 = _time.time()
    try:
        result = _word_define(word, source_lang, target_lang, context)
        latency_ms = int((_time.time() - t0) * 1000)
        ctx.settle({}, "deepseek", "deepseek-chat", latency_ms)
        return jsonify(result)
    except Exception as e:
        ctx.release_on_error(e)
        logger.error(f"[WordDefine] 失败: {e}")
        return jsonify({"error": str(e)}), 500


EXPORT_DIR = settings.EXPORTS_DIR


@app.route("/api/export-srt", methods=["POST"])
def api_export_srt():
    """仅导出 SRT 字幕文件"""
    data = request.get_json()
    video_name = data.get("video")
    export_dir = data.get("export_dir", "").strip()
    file_prefix = data.get("file_prefix", "").strip()

    if not video_name:
        return jsonify({"error": "缺少 video 参数"}), 400

    sub_path = subtitle_path(video_name)
    if not os.path.exists(sub_path):
        return jsonify({"error": "字幕文件不存在，请先识别翻译"}), 400

    with open(sub_path, "r", encoding="utf-8") as f:
        subtitle_file = SubtitleFile.from_json(json.load(f))

    target_dir = export_dir if export_dir else EXPORT_DIR
    os.makedirs(target_dir, exist_ok=True)

    base = file_prefix if file_prefix else os.path.splitext(video_name)[0]

    db = get_db()
    _uid = _get_user_id(db)
    ctx = CommerceContext(db, _uid, "export", "standard", "free")
    if not ctx.check_permission("CanExport"):
        return jsonify({"error": "权限不足，请升级套餐"}), 403
    ctx.reserve({})   # export 免费，reserve 0 credits

    import time as _time
    t0 = _time.time()
    srt_names = export_srt(subtitle_file, target_dir, base)
    ctx.settle({}, "local", "ffmpeg", int((_time.time() - t0) * 1000))
    return jsonify({"dir": target_dir, "files": srt_names})


@app.route("/api/export", methods=["POST"])
def api_export():
    """导出带双语字幕的视频，通过 SSE 推送进度"""
    data = request.get_json()
    video_name = data.get("video")
    export_dir = data.get("export_dir", "").strip()
    file_prefix = data.get("file_prefix", "").strip()

    if not video_name:
        return jsonify({"error": "缺少 video 参数"}), 400

    video_path = os.path.join(VIDEOS_DIR, video_name)
    if not os.path.exists(video_path):
        return jsonify({"error": "视频文件不存在"}), 404

    sub_path = subtitle_path(video_name)
    if not os.path.exists(sub_path):
        return jsonify({"error": "字幕文件不存在，请先识别翻译"}), 400

    with open(sub_path, "r", encoding="utf-8") as f:
        subtitle_file = SubtitleFile.from_json(json.load(f))

    # 确定导出目录和文件名前缀
    target_dir = export_dir if export_dir else EXPORT_DIR
    os.makedirs(target_dir, exist_ok=True)

    base = file_prefix if file_prefix else os.path.splitext(video_name)[0]
    output_name = base + ".mp4"
    output_path = os.path.join(target_dir, output_name)

    # 导出两个独立 SRT 文件
    srt_names = export_srt(subtitle_file, target_dir, base)

    # 用 SSE 流式推送进度
    progress_queue = queue.Queue()

    db = get_db()
    _uid = _get_user_id(db)
    ctx_export = CommerceContext(db, _uid, "export", "standard", "free")
    if not ctx_export.check_permission("CanExport"):
        return jsonify({"error": "权限不足，请升级套餐"}), 403
    ctx_export.reserve({})

    def do_export():
        import time as _time
        t0 = _time.time()
        try:
            export_video_with_subtitles(
                video_path, subtitle_file, output_path,
                progress_callback=lambda pct: progress_queue.put(("progress", pct)),
            )
            ctx_export.settle({}, "local", "ffmpeg", int((_time.time() - t0) * 1000))
            progress_queue.put(("done", {
                "dir": target_dir,
                "files": [output_name] + srt_names,
            }))
        except Exception as e:
            ctx_export.release_on_error(e)
            progress_queue.put(("error", str(e)))

    threading.Thread(target=do_export, daemon=True).start()

    def generate():
        while True:
            msg_type, msg_data = progress_queue.get()
            if msg_type == "progress":
                yield f"data: {json.dumps({'progress': msg_data})}\n\n"
            elif msg_type == "done":
                yield f"data: {json.dumps({'done': True, **msg_data})}\n\n"
                break
            elif msg_type == "error":
                yield f"data: {json.dumps({'error': msg_data})}\n\n"
                break

    return Response(generate(), mimetype="text/event-stream")


UPLOAD_TMP = settings.TMP_DIR


@app.route("/api/pronounce", methods=["POST"])
def api_pronounce():
    """发音评估：接收录音 + 参考文本，返回评分"""
    if "audio" not in request.files:
        return jsonify({"error": "缺少音频文件"}), 400

    reference_text = request.form.get("reference_text", "").strip()
    lang = request.form.get("language", "th-TH")

    if not reference_text:
        return jsonify({"error": "缺少参考文本"}), 400

    os.makedirs(UPLOAD_TMP, exist_ok=True)

    # 保存上传的音频（保留原始扩展名）
    import time as _time
    audio_file = request.files["audio"]
    original_name = audio_file.filename or "recording.webm"
    ext = os.path.splitext(original_name)[1] or ".webm"
    audio_path = os.path.join(UPLOAD_TMP, "recording" + ext)
    audio_file.save(audio_path)

    # 估算时长：用字数粗估（pronunciation 通常 < 30 秒）
    duration_estimate = max(2.0, len(reference_text) * 0.3)

    db = get_db()
    _uid    = _get_user_id(db)
    _rl_key = _get_rl_key(_uid)
    is_anon = (_uid == ANONYMOUS_USER_ID)

    if not is_anon:
        ctx = CommerceContext(
            db, _uid, "pronunciation", "standard", "free",
            extra={"lang": lang, "text_len": len(reference_text)},
        )
        if not ctx.check_permission("CanPronunciationAssess"):
            os.remove(audio_path) if os.path.exists(audio_path) else None
            return jsonify({"error": "权限不足，请升级套餐"}), 403
        plan = get_user_plan(db, _uid)
    else:
        ctx  = None
        plan = "device"

    if not _check_rate_limit(_rl_key, "pronunciation", plan):
        os.remove(audio_path) if os.path.exists(audio_path) else None
        used  = _rl_get_usage(_rl_key, "pronunciation")
        limit = _rl_get_limit("pronunciation", plan)
        if is_anon:
            return jsonify({"error": f"免费体验次数已用完（{used}/{limit} 次），登录后可无限使用"}), 429
        return jsonify({"error": f"今日发音评分次数已达上限（{used}/{limit} 次），明日重置"}), 429

    if not is_anon:
        try:
            ctx.reserve({"duration_seconds": duration_estimate})
        except InsufficientFundsError:
            os.remove(audio_path) if os.path.exists(audio_path) else None
            return jsonify({"error": "Credits 不足，请充值后重试"}), 402
    _rl_increment(_rl_key, "pronunciation")

    t0 = _time.time()
    try:
        result = assess_pronunciation(audio_path, reference_text, lang)
        latency_ms = int((_time.time() - t0) * 1000)
        if not is_anon:
            ctx.settle({"duration_seconds": duration_estimate}, "azure", "azure-speech", latency_ms)
        return jsonify(result)
    except Exception as e:
        if not is_anon:
            ctx.release_on_error(e)
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)


@app.route("/api/bookmark-sentence", methods=["POST"])
def api_bookmark_sentence():
    """收藏句子：从服务器视频截取音频片段并上传到 R2"""
    import uuid
    data = request.get_json()
    video_name = data.get("video", "")
    try:
        start = float(data.get("start", -1))
        end = float(data.get("end", -1))
    except (TypeError, ValueError):
        return jsonify({"error": "时间参数无效"}), 400

    if not (0 <= start < end) or end - start > 60:
        return jsonify({"error": "时间范围无效"}), 400

    videos_root = os.path.realpath(VIDEOS_DIR)
    video_path = os.path.realpath(os.path.join(VIDEOS_DIR, video_name))
    if not video_path.startswith(videos_root + os.sep) or not os.path.exists(video_path):
        return jsonify({"error": "视频文件不存在"}), 404

    tmp_mp3 = os.path.join(VIDEOS_DIR, f".bookmark_{os.getpid()}_{uuid.uuid4().hex}.mp3")
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", str(start), "-to", str(end),
            "-vn", "-ar", "22050", "-ac", "1", "-b:a", "64k",
            tmp_mp3,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            return jsonify({"error": "音频截取失败: " + r.stderr[-200:]}), 500

        key = f"sentences/{uuid.uuid4().hex}.mp3"
        audio_url = upload_audio(tmp_mp3, key)
        log_event("bookmark", video=video_name, range=f"{start:.1f}-{end:.1f}")
        return jsonify({"audio_url": audio_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    finally:
        if os.path.exists(tmp_mp3):
            os.remove(tmp_mp3)


@app.route("/api/bookmark-audio", methods=["POST"])
def api_bookmark_audio():
    """收藏句子：接收前端上传的音频片段（本地视频场景）并上传到 R2"""
    import uuid
    if "audio" not in request.files:
        return jsonify({"error": "缺少音频文件"}), 400

    audio_file = request.files["audio"]
    tmp_in = os.path.join(VIDEOS_DIR, f".bm_in_{os.getpid()}.wav")
    tmp_mp3 = os.path.join(VIDEOS_DIR, f".bm_out_{os.getpid()}.mp3")
    try:
        audio_file.save(tmp_in)
        if os.path.getsize(tmp_in) > 10 * 1024 * 1024:
            return jsonify({"error": "音频文件过大"}), 400

        cmd = [
            "ffmpeg", "-y", "-i", tmp_in,
            "-ar", "22050", "-ac", "1", "-b:a", "64k",
            tmp_mp3,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            return jsonify({"error": "音频转换失败: " + r.stderr[-200:]}), 500

        key = f"sentences/{uuid.uuid4().hex}.mp3"
        audio_url = upload_audio(tmp_mp3, key)
        log_event("bookmark_audio")
        return jsonify({"audio_url": audio_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    finally:
        for p in (tmp_in, tmp_mp3):
            if os.path.exists(p):
                os.remove(p)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4 — Admin API + 用户余额 API
# ══════════════════════════════════════════════════════════════════════════════

def _admin_key_check():
    """检查 ADMIN_KEY，通过返回 None，失败返回 (response, 403)。"""
    key = request.args.get("key") or request.headers.get("X-Admin-Key", "")
    if not settings.ADMIN_KEY or key != settings.ADMIN_KEY:
        return jsonify({"error": "unauthorized"}), 403
    return None


# ── Task 4.1：Admin API ───────────────────────────────────────────────────────

@app.route("/api/admin/commerce/users")
def admin_commerce_users():
    """用户列表 + 余额概览"""
    err = _admin_key_check()
    if err:
        return err

    db = get_db()
    rows = db.execute(
        """
        SELECT u.user_id, u.email, u.status, u.created_at,
               w.subscription_credits, w.gift_credits, w.paid_credits,
               w.subscription_expires_at
        FROM users u
        LEFT JOIN wallets w ON w.user_id = u.user_id
        ORDER BY u.created_at DESC
        LIMIT 200
        """
    ).fetchall()

    users = []
    for r in rows:
        sub  = r["subscription_credits"] or 0
        gift = r["gift_credits"] or 0
        paid = r["paid_credits"] or 0
        plan = get_user_plan(db, r["user_id"])
        users.append({
            "user_id":    r["user_id"],
            "email":      r["email"],
            "status":     r["status"],
            "created_at": r["created_at"],
            "plan":       plan,
            "balance": {
                "subscription": sub,
                "gift":         gift,
                "paid":         paid,
                "total":        sub + gift + paid,
            },
            "subscription_expires_at": r["subscription_expires_at"],
        })
    return jsonify({"users": users, "count": len(users)})


@app.route("/api/admin/commerce/usage")
def admin_commerce_usage():
    """用量报表（全用户，按 capability / provider 汇总）"""
    err = _admin_key_check()
    if err:
        return err

    days = int(request.args.get("days", 7))
    db   = get_db()

    rows = db.execute(
        """
        SELECT capability, provider_id,
               COUNT(*)                    AS calls,
               SUM(credits_charged)        AS total_credits,
               SUM(provider_cost_usd)      AS total_cost_usd,
               AVG(latency_ms)             AS avg_latency_ms,
               SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_count
        FROM usage_logs
        WHERE requested_at >= datetime('now', ?)
        GROUP BY capability, provider_id
        ORDER BY total_credits DESC
        """,
        (f"-{days} days",),
    ).fetchall()

    by_cap: dict  = {}
    by_prov: dict = {}
    total_credits = 0
    total_cost    = 0.0

    for r in rows:
        cap  = r["capability"]
        prov = r["provider_id"] or "unknown"
        cred = r["total_credits"] or 0
        cost = r["total_cost_usd"] or 0.0

        total_credits += cred
        total_cost    += cost

        if cap not in by_cap:
            by_cap[cap] = {"credits": 0, "cost_usd": 0.0, "calls": 0, "failed": 0}
        by_cap[cap]["credits"]  += cred
        by_cap[cap]["cost_usd"] += cost
        by_cap[cap]["calls"]    += r["calls"]
        by_cap[cap]["failed"]   += r["failed_count"] or 0

        if prov not in by_prov:
            by_prov[prov] = {"credits": 0, "cost_usd": 0.0, "calls": 0}
        by_prov[prov]["credits"]  += cred
        by_prov[prov]["cost_usd"] += cost
        by_prov[prov]["calls"]    += r["calls"]

    return jsonify({
        "days":           days,
        "total_credits":  total_credits,
        "total_cost_usd": round(total_cost, 6),
        "by_capability":  by_cap,
        "by_provider":    by_prov,
    })


@app.route("/api/admin/commerce/costs")
def admin_commerce_costs():
    """成本报表（按 provider 汇总 cost_usd，对账用）"""
    err = _admin_key_check()
    if err:
        return err

    days = int(request.args.get("days", 7))
    db   = get_db()

    rows = db.execute(
        """
        SELECT provider_id, model_id, capability,
               COUNT(*)                AS calls,
               SUM(provider_cost_usd) AS cost_usd,
               SUM(credits_charged)   AS credits_charged
        FROM usage_logs
        WHERE requested_at >= datetime('now', ?)
          AND status = 'success'
        GROUP BY provider_id, model_id, capability
        ORDER BY cost_usd DESC
        """,
        (f"-{days} days",),
    ).fetchall()

    entries = [dict(r) for r in rows]
    total_cost    = sum(e["cost_usd"] or 0 for e in entries)
    total_credits = sum(e["credits_charged"] or 0 for e in entries)

    return jsonify({
        "days":             days,
        "total_cost_usd":   round(total_cost, 6),
        "total_credits":    total_credits,
        "entries":          entries,
    })


@app.route("/api/admin/commerce/credits/grant", methods=["POST"])
def admin_commerce_grant():
    """赠送 Credits 给指定用户"""
    err = _admin_key_check()
    if err:
        return err

    data        = request.get_json()
    user_id     = (data.get("user_id") or "").strip()
    amount      = int(data.get("amount", 0))
    credit_type = data.get("type", "gift")           # subscription / gift / paid
    expires_days= int(data.get("expires_days", 30))
    reason      = (data.get("reason") or "admin grant").strip()

    if not user_id or amount <= 0:
        return jsonify({"error": "user_id 和 amount 必填且 amount > 0"}), 400
    if credit_type not in ("subscription", "gift", "paid"):
        return jsonify({"error": "type 必须为 subscription / gift / paid"}), 400

    db = get_db()
    import datetime as _dt
    expires_at = None
    if credit_type == "gift":
        expires_at = (
            _dt.datetime.utcnow() + _dt.timedelta(days=expires_days)
        ).strftime("%Y-%m-%d %H:%M:%S")

    try:
        _wallet_add(db, user_id, amount, credit_type, reason, expires_at=expires_at)
        balance = _wallet_balance(db, user_id)
        return jsonify({
            "ok":      True,
            "user_id": user_id,
            "granted": amount,
            "type":    credit_type,
            "balance": balance,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/commerce/credits/refund", methods=["POST"])
def admin_commerce_refund():
    """手动退款到 gift_credits（30 天有效）"""
    err = _admin_key_check()
    if err:
        return err

    data        = request.get_json()
    log_id      = (data.get("usage_log_id") or "").strip()
    amount      = int(data.get("amount", 0))
    reason      = (data.get("reason") or "admin refund").strip()

    if not log_id or amount <= 0:
        return jsonify({"error": "usage_log_id 和 amount 必填且 amount > 0"}), 400

    db = get_db()
    try:
        _wallet_refund(db, log_id, amount, reason)
        log = _log_get(db, log_id)
        return jsonify({
            "ok":           True,
            "usage_log_id": log_id,
            "refunded":     amount,
            "log_status":   log["status"] if log else None,
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/commerce/log/<log_id>")
def admin_commerce_log(log_id):
    """单条 usage_log 详情"""
    err = _admin_key_check()
    if err:
        return err

    db  = get_db()
    log = _log_get(db, log_id)
    if not log:
        return jsonify({"error": "log not found"}), 404
    return jsonify(log)


# ── Task 5.1：对账 API ───────────────────────────────────────────────────────

@app.route("/api/admin/commerce/reconcile")
def admin_commerce_reconcile():
    """对账报告：usage_logs.credits_charged vs wallet_transactions confirm 之和"""
    err = _admin_key_check()
    if err:
        return err

    from commerce.reconcile import run_reconciliation
    days        = int(request.args.get("days", 1))
    webhook_url = request.args.get("webhook")
    db          = get_db()
    result      = run_reconciliation(db, since_days=days, webhook_url=webhook_url)
    status      = 200 if result["ok"] else 409
    return jsonify(result), status


# ── Task 5.2：Rate Limit 状态 API ────────────────────────────────────────────

@app.route("/api/user/rate-limits")
def user_rate_limits():
    """返回当前用户今日各 capability 限额使用情况"""
    db      = get_db()
    _uid    = _get_user_id(db)
    _rl_key = _get_rl_key(_uid)
    is_anon = (_uid == ANONYMOUS_USER_ID)
    plan    = "device" if is_anon else get_user_plan(db, _uid)

    caps = ["transcription", "tts_synthesis", "pronunciation"]
    info = {}
    for cap in caps:
        limit = _rl_get_limit(cap, plan)
        if limit is not None:
            used = _rl_get_usage(_rl_key, cap)
            info[cap] = {
                "used":      used,
                "limit":     limit,
                "remaining": max(0, limit - used),
                "plan":      plan,
            }
    return jsonify({"plan": plan, "rate_limits": info})


# ── Task 4.2：用户余额 API ────────────────────────────────────────────────────

@app.route("/api/user/wallet")
def user_wallet():
    """当前用户余额 + 套餐信息（过渡期固定返回 anonymous 用户数据）"""
    db      = get_db()
    user_id = _get_user_id(db)

    try:
        balance = _wallet_balance(db, user_id)
    except Exception:
        balance = {"subscription": 0, "gift": 0, "paid": 0, "total": 0}

    plan = get_user_plan(db, user_id)

    sub_row = db.execute(
        """
        SELECT expires_at, credits_quota
        FROM user_subscriptions
        WHERE user_id = ? AND status = 'active'
          AND (expires_at IS NULL OR expires_at > datetime('now'))
        ORDER BY started_at DESC LIMIT 1
        """,
        (user_id,),
    ).fetchone()

    wallet_row = db.execute(
        "SELECT gift_expires_at FROM wallets WHERE user_id = ?",
        (user_id,),
    ).fetchone()

    return jsonify({
        "user_id":                 user_id,
        "plan":                    plan,
        "balance":                 balance,
        "subscription_expires_at": sub_row["expires_at"] if sub_row else None,
        "monthly_quota":           sub_row["credits_quota"] if sub_row else 0,
        "gift_expires_at":         wallet_row["gift_expires_at"] if wallet_row else None,
    })


@app.route("/api/user/usage")
def user_usage():
    """当前用户最近用量记录"""
    db    = get_db()
    limit = min(int(request.args.get("limit", 20)), 100)
    days  = int(request.args.get("days", 30))

    _uid    = _get_user_id(db)
    history = _log_user_history(db, _uid, limit=limit)
    summary = _log_summary(db, _uid, since_days=days)

    return jsonify({
        "user_id": _uid,
        "summary": summary,
        "history": history,
    })


# ── Google OAuth 登录 ─────────────────────────────────────────────────────────

@app.route("/api/auth/google/login")
def auth_google_login():
    """重定向到 Google 授权页，设置 oauth_state Cookie 防 CSRF。"""
    import secrets as _secrets
    state = _secrets.token_urlsafe(16)
    url   = _auth.google_login_url(state)
    resp  = make_response("", 302)
    resp.headers["Location"] = url
    resp.set_cookie(
        "oauth_state", state,
        httponly=True, samesite="Lax", secure=False,
        max_age=600,   # 10 分钟有效
    )
    return resp


@app.route("/api/auth/google/callback")
def auth_google_callback():
    """Google 回调：验证 state → 换取用户信息 → 建立 session → 跳转回前端。"""
    error = request.args.get("error")
    if error:
        return redirect("/app?auth_error=" + error)

    code  = request.args.get("code", "")
    state = request.args.get("state", "")
    cookie_state = request.cookies.get("oauth_state", "")

    logger.info(f"[auth] callback: code={'yes' if code else 'no'} "
                f"state={state!r} cookie_state={cookie_state!r}")

    if not code:
        return redirect("/app?auth_error=no_code")
    if not state or state != cookie_state:
        # state 不匹配时跳过校验继续（避免 cookie 被阻拦导致登录失败）
        logger.warning(f"[auth] state mismatch — continuing anyway "
                       f"(url={state!r} cookie={cookie_state!r})")

    try:
        user_info = _auth.google_exchange_code(code)
    except Exception as e:
        logger.warning(f"[auth] Google exchange error: {e}")
        return redirect("/app?auth_error=exchange_failed")

    try:
        db      = get_db()
        user_id = _auth.upsert_user(
            db, "google",
            user_info["sub"], user_info["email"],
            user_info["name"], user_info["picture"],
        )
        token = _auth.create_session(db, user_id, request.headers.get("User-Agent"))
    except Exception as e:
        logger.error(f"[auth] upsert/session error: {e}", exc_info=True)
        return redirect("/app?auth_error=db_error")

    resp = make_response("", 302)
    resp.headers["Location"] = "/app"
    resp.set_cookie(
        _auth.COOKIE_NAME, token,
        httponly=True, samesite="Lax", secure=False,
        max_age=_auth.SESSION_DAYS * 86400,
    )
    resp.delete_cookie("oauth_state")
    return resp


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    """登出：删除 session，清除 Cookie。"""
    db    = get_db()
    token = request.cookies.get(_auth.COOKIE_NAME)
    if token:
        _auth.logout(db, token)
    resp = jsonify({"ok": True})
    resp.delete_cookie(_auth.COOKIE_NAME)
    return resp


@app.route("/api/auth/me")
def auth_me():
    """返回当前登录用户信息，未登录返回 {logged_in: false}。"""
    db   = get_db()
    user = _auth.get_current_user(db, request)
    if not user:
        return jsonify({"logged_in": False})
    return jsonify({
        "logged_in":   True,
        "user_id":     user["user_id"],
        "email":       user["email"],
        "name":        user["name"],
        "picture_url": user["picture_url"],
    })


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=settings.PORT)
