import os
import json
import queue
import re
import subprocess
import threading
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from dotenv import load_dotenv
from transcribe import transcribe_video, transcribe_slice, add_word_spacing, align_word_timestamps
from translate import translate_segments
from export import export_video_with_subtitles, export_srt
from pronounce import assess_pronunciation
from tts import generate_audio_lesson, generate_cover_image, ocr_image

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

app = Flask(__name__)
CORS(app)


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

VIDEOS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "videos")
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")


def subtitle_path(video_name):
    """视频对应的字幕 JSON 文件路径"""
    base = os.path.splitext(video_name)[0]
    return os.path.join(VIDEOS_DIR, base + ".json")


# ========== 使用日志（开发者分析用） ==========
USAGE_LOG = os.path.join(VIDEOS_DIR, "usage_log.jsonl")


def log_event(kind, **data):
    """记录一条使用事件：写文件 + 打印 stdout（Railway 控制台可查看）"""
    import datetime
    record = {
        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": kind,
        **data,
    }
    line = json.dumps(record, ensure_ascii=False)
    print(f"[USAGE] {line}", flush=True)
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
        "-af", "afftdn=nr=10:nf=-25,loudnorm=I=-14:TP=-1.5:LRA=11",
        "-c:a", "aac", "-b:a", "128k",
        tmp_path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode == 0 and os.path.getsize(tmp_path) > 0:
            os.replace(tmp_path, video_path)
            return True
        print(f"[Normalize] 失败: {r.stderr[-200:]}")
    except Exception as e:
        print(f"[Normalize] 异常: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return False



@app.route("/api/admin/logs")
def admin_logs():
    """开发者查看使用日志（需要 ADMIN_KEY）"""
    admin_key = os.environ.get("ADMIN_KEY", "")
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


@app.route("/")
def landing():
    return send_from_directory(FRONTEND_DIR, "landing.html")


@app.route("/app")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


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


@app.route("/api/download-video", methods=["POST"])
def api_download_video():
    """从 URL 下载视频到 videos 目录，通过 SSE 推送进度"""
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "缺少视频链接"}), 400

    log_event("download", url=url)

    os.makedirs(VIDEOS_DIR, exist_ok=True)

    progress_queue = queue.Queue()

    def ytdlp_cookie_args():
        """YouTube 数据中心 IP 反爬兜底：支持通过环境变量注入 cookies"""
        cookies = os.environ.get("YOUTUBE_COOKIES", "")
        if not cookies:
            return []
        cookie_file = os.path.join(os.path.dirname(__file__), ".yt_cookies.txt")
        try:
            with open(cookie_file, "w", encoding="utf-8") as f:
                f.write(cookies)
            return ["--cookies", cookie_file]
        except Exception:
            return []

    def do_download():
        try:
            cookie_args = ytdlp_cookie_args()
            extra_args = list(cookie_args)

            # 先获取视频标题作为文件名
            info_cmd = ["yt-dlp", "--no-download", "--print", "title"] + extra_args + [url]
            info_result = subprocess.run(
                info_cmd, capture_output=True, text=True, timeout=30
            )
            if info_result.returncode != 0 and (
                "Sign in" in info_result.stderr or "cookies" in info_result.stderr
            ):
                # YouTube 机器人检测：改用 TV 客户端伪装重试
                progress_queue.put(("progress", "YouTube 验证拦截，尝试备用通道..."))
                extra_args = cookie_args + ["--extractor-args", "youtube:player_client=tv,web_embedded"]
                info_cmd = ["yt-dlp", "--no-download", "--print", "title"] + extra_args + [url]
                info_result = subprocess.run(
                    info_cmd, capture_output=True, text=True, timeout=30
                )
            if info_result.returncode != 0:
                err = info_result.stderr[-300:]
                if "Sign in" in err or "cookies" in err:
                    err = "YouTube 阻止了服务器访问（反爬验证）。请改用 TikTok 链接，或联系开发者配置 YouTube cookies。"
                progress_queue.put(("error", f"无法获取视频信息: {err}"))
                return

            title = info_result.stdout.strip()
            # 清理文件名
            safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)[:80]
            if not safe_title:
                safe_title = "downloaded_video"

            output_path = os.path.join(VIDEOS_DIR, safe_title + ".mp4")

            # 如果已存在，直接返回
            if os.path.exists(output_path):
                progress_queue.put(("done", {
                    "name": safe_title + ".mp4",
                    "message": "视频已存在，无需重复下载",
                }))
                return

            progress_queue.put(("progress", f"正在下载: {title}"))

            # 下载视频（沿用信息获取阶段成功的通道参数）
            dl_cmd = [
                "yt-dlp",
                "-f", "mp4/best[ext=mp4]/best",
                "--merge-output-format", "mp4",
                "--no-playlist",
                "-o", output_path,
                "--progress",
                "--newline",
            ] + extra_args + [url]
            process = subprocess.Popen(
                dl_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )

            pct_re = re.compile(r"(\d+\.?\d*)%")
            for line in process.stdout:
                line = line.strip()
                match = pct_re.search(line)
                if match:
                    pct = float(match.group(1))
                    progress_queue.put(("progress", f"下载中... {pct:.0f}%"))

            process.wait()
            if process.returncode != 0:
                progress_queue.put(("error", "下载失败，请检查链接是否正确"))
                return

            # 检查文件是否存在（yt-dlp 可能改了文件名）
            if not os.path.exists(output_path):
                # 尝试查找 yt-dlp 实际生成的文件
                for f in os.listdir(VIDEOS_DIR):
                    if f.startswith(safe_title) and f.endswith(".mp4"):
                        output_path = os.path.join(VIDEOS_DIR, f)
                        safe_title = f.replace(".mp4", "")
                        break

            if os.path.exists(output_path):
                # 响度归一化 + 降噪（源片音量低时对齐 TikTok 播放响度）
                progress_queue.put(("progress", "正在优化音质（响度归一化 + 降噪）..."))
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
    """语音识别 + 断句"""
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

    try:
        result = transcribe_video(video_path, provider=provider,
                                  segment_target=segment_target)

        # 泰语等无空格语言：用 Gemini 按词加空格，方便学习者阅读
        lang = (result.get("language") or "")[:2].lower()
        lang_full = (result.get("language") or "").lower()
        if lang == "th" or lang_full == "thai":
            raw_words = result.get("words", [])
            if raw_words:
                # 直接用 OpenAI 词级 tokens 构建带空格文本（跳过 Gemini）
                for s in result["segments"]:
                    seg_words = [w for w in raw_words
                                 if w["start"] >= s["start"] - 0.05
                                 and w["end"] <= s["end"] + 0.05]
                    if seg_words:
                        s["text"] = " ".join(w["word"].strip() for w in seg_words)
                align_word_timestamps(result["segments"], raw_words)
                result.pop("words", None)
            else:
                # 无词级 tokens 时才用 Gemini（非 OpenAI 引擎的兜底）
                texts = [s["text"] for s in result["segments"]]
                spaced = add_word_spacing(texts, "th")
                for s, sp in zip(result["segments"], spaced):
                    s["text"] = sp

        # 清理内部字段，保留前端需要的置信度信息
        for s in result.get("segments", []):
            if "_conf" in s:
                s["confidence"] = s.pop("_conf")
            if "_source" in s:
                s["source"] = s.pop("_source")
            s.pop("_logprob", None)
            s.pop("_no_speech", None)
        result.pop("words", None)

        log_event("transcribe", video=video_name, provider=provider,
                  language=result.get("language", ""),
                  segments=len(result.get("segments", [])))
        return jsonify(result)
    except Exception as e:
        log_event("transcribe_fail", video=video_name, provider=provider, error=str(e)[:200])
        return jsonify({"error": str(e)}), 500


@app.route("/api/retranscribe", methods=["POST"])
def api_retranscribe():
    """对视频的一个时间片段进行二次识别（用户微调时间戳后重新识别单句）"""
    data = request.get_json()
    video_name = data.get("video", "")
    provider = data.get("provider", "groq")
    do_translate = bool(data.get("translate", True))
    source_lang = data.get("source_lang", "泰语")
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

        result = transcribe_slice(wav_path, provider, language=language)
        text = result["text"]

        # 泰语：按词加空格
        if (language or "")[:2].lower() == "th" and text:
            text = add_word_spacing([text], "th")[0]

        translation = ""
        if do_translate and text:
            try:
                translated = translate_segments([{"index": 0, "text": text}], source_lang, "中文")
                if translated:
                    translation = translated[0].get("translation", "")
            except Exception as te:
                print(f"[Retranscribe] 翻译失败: {te}")

        log_event("retranscribe", video=video_name, provider=provider,
                  range=f"{start:.1f}-{end:.1f}", language=language)
        return jsonify({"text": text, "translation": translation})
    except Exception as e:
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
                translated = translate_segments([{"index": 0, "text": text}], source_lang, "中文")
                if translated:
                    translation = translated[0].get("translation", "")
            except Exception as te:
                print(f"[RetranscribeAudio] 翻译失败: {te}")

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
    if "image" not in request.files:
        return jsonify({"error": "缺少图片"}), 400
    img = request.files["image"]
    data = img.read()
    if len(data) > 10 * 1024 * 1024:
        return jsonify({"error": "图片过大（最多 10MB）"}), 400
    mime = img.mimetype or "image/png"
    language = request.form.get("language", "")
    try:
        text = ocr_image(data, mime, language)
        log_event("ocr", language=language, chars=len(text))
        return jsonify({"text": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/tts-generate", methods=["POST"])
def api_tts_generate():
    """粘贴文本 → 生成语音课程（音频 + 逐句时间戳字幕）"""
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
    try:
        # language="auto" 时返回的是检测到的语言
        audio_name, segments, language = generate_audio_lesson(
            text, language, engine, VIDEOS_DIR
        )
        source_lang_name = {"th": "泰语", "en": "英语", "zh": "中文",
                            "ja": "日语", "ko": "韩语"}.get(language, "外语")

        # 泰语：显示文本按词加空格 + 发音时长权重（朗读音频已用原文生成，不受影响）
        if language == "th":
            texts = [s["text"] for s in segments]
            spaced = add_word_spacing(texts, "th")
            for s, sp in zip(segments, spaced):
                s["text"] = sp

        # 翻译（目标语言由前端界面语言决定；源语言与目标一致时跳过）
        target_lang = data.get("target_lang", "中文")
        same_lang = (language == "zh" and target_lang in ("中文", "繁體中文")) or \
                    (language == "ja" and target_lang == "日本語") or \
                    (language == "ko" and target_lang == "한국어") or \
                    (language == "en" and target_lang == "English")
        if not same_lang:
            try:
                translated = translate_segments(
                    [{"index": s["index"], "text": s["text"]} for s in segments],
                    source_lang_name, target_lang,
                )
                for tr in translated:
                    idx = tr.get("index")
                    if idx is not None and 0 <= idx < len(segments):
                        segments[idx]["translation"] = tr.get("translation", "")
            except Exception as te:
                print(f"[TTS] 翻译失败: {te}")

        # 封面插画（卡通风格，根据文本内容生成；失败不影响主流程）
        cover_name = os.path.splitext(audio_name)[0] + ".jpg"
        cover = ""
        if generate_cover_image(text, language, os.path.join(VIDEOS_DIR, cover_name)):
            cover = cover_name

        # 落盘字幕 JSON（与视频字幕同格式，播放器直接复用）
        subtitle_data = {"segments": segments, "language": language}
        if cover:
            subtitle_data["cover"] = cover
        with open(subtitle_path(audio_name), "w", encoding="utf-8") as f:
            json.dump(subtitle_data, f, ensure_ascii=False, indent=2)

        log_event("tts_generate", engine=engine, language=language,
                  chars=len(text), sentences=len(segments))
        return jsonify({"name": audio_name, "segments": segments,
                        "language": language, "cover": cover})
    except Exception as e:
        log_event("tts_generate_fail", engine=engine, error=str(e)[:200])
        return jsonify({"error": str(e)}), 502


@app.route("/api/translate", methods=["POST"])
def api_translate():
    """翻译句子"""
    data = request.get_json()
    segments = data.get("segments", [])
    source_lang = data.get("source_lang", "泰语")
    target_lang = data.get("target_lang", "中文")

    if not segments:
        return jsonify({"error": "缺少 segments 参数"}), 400

    try:
        translations = translate_segments(segments, source_lang, target_lang)
        return jsonify({"translations": translations})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/word-define", methods=["POST"])
def api_word_define():
    """查询单词释义（DeepSeek）"""
    data = request.get_json()
    word = (data.get("word") or "").strip()
    source_lang = data.get("source_lang", "泰语")
    target_lang = data.get("target_lang", "中文")
    context = (data.get("context") or "").strip()

    if not word:
        return jsonify({"error": "缺少 word 参数"}), 400

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return jsonify({"error": "未配置 DEEPSEEK_API_KEY"}), 500

    ctx_hint = f'\n该词出现在以下句子中："{context}"' if context else ""
    prompt = (
        f"请用{target_lang}简洁解释以下{source_lang}单词的含义。{ctx_hint}\n"
        f"单词：{word}\n\n"
        f"严格按 JSON 返回，格式：{{\"meaning\": \"释义\", \"pos\": \"词性\"}}\n"
        f"释义不超过15个字，词性用缩写（n./v./adj./adv./conj./prep./pron./interj.）。\n"
        f"只返回 JSON，不要其他文字。"
    )

    try:
        import requests as req
        resp = req.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2},
            timeout=15,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        import json as _json
        result = _json.loads(content)
        return jsonify(result)
    except Exception as e:
        print(f"[WordDefine] 失败: {e}")
        return jsonify({"error": str(e)}), 500


EXPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "exports")


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
        subtitle_data = json.load(f)

    target_dir = export_dir if export_dir else EXPORT_DIR
    os.makedirs(target_dir, exist_ok=True)

    base = file_prefix if file_prefix else os.path.splitext(video_name)[0]
    lang = subtitle_data.get("language", "")
    srt_names = export_srt(subtitle_data, target_dir, base, lang)

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
        subtitle_data = json.load(f)

    # 确定导出目录和文件名前缀
    target_dir = export_dir if export_dir else EXPORT_DIR
    os.makedirs(target_dir, exist_ok=True)

    base = file_prefix if file_prefix else os.path.splitext(video_name)[0]
    output_name = base + ".mp4"
    output_path = os.path.join(target_dir, output_name)

    # 导出两个独立 SRT 文件
    lang = subtitle_data.get("language", "")
    srt_names = export_srt(subtitle_data, target_dir, base, lang)

    # 用 SSE 流式推送进度
    progress_queue = queue.Queue()

    def do_export():
        try:
            export_video_with_subtitles(
                video_path, subtitle_data, output_path,
                progress_callback=lambda pct: progress_queue.put(("progress", pct)),
            )
            progress_queue.put(("done", {
                "dir": target_dir,
                "files": [output_name] + srt_names,
            }))
        except Exception as e:
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


UPLOAD_TMP = os.path.join(os.path.dirname(__file__), "tmp")


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
    audio_file = request.files["audio"]
    original_name = audio_file.filename or "recording.webm"
    ext = os.path.splitext(original_name)[1] or ".webm"
    audio_path = os.path.join(UPLOAD_TMP, "recording" + ext)
    audio_file.save(audio_path)

    try:
        result = assess_pronunciation(audio_path, reference_text, lang)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
