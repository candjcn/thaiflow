import os
import json
import queue
import re
import subprocess
import threading
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from dotenv import load_dotenv
from transcribe import transcribe_video
from translate import translate_segments
from export import export_video_with_subtitles, export_srt
from pronounce import assess_pronunciation

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

app = Flask(__name__)
CORS(app)

VIDEOS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "videos")
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")


def subtitle_path(video_name):
    """视频对应的字幕 JSON 文件路径"""
    base = os.path.splitext(video_name)[0]
    return os.path.join(VIDEOS_DIR, base + ".json")


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


@app.route("/api/download-video", methods=["POST"])
def api_download_video():
    """从 URL 下载视频到 videos 目录，通过 SSE 推送进度"""
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "缺少视频链接"}), 400

    os.makedirs(VIDEOS_DIR, exist_ok=True)

    progress_queue = queue.Queue()

    def do_download():
        try:
            # 先获取视频标题作为文件名
            info_cmd = [
                "yt-dlp", "--no-download", "--print", "title", url
            ]
            info_result = subprocess.run(
                info_cmd, capture_output=True, text=True, timeout=30
            )
            if info_result.returncode != 0:
                progress_queue.put(("error", f"无法获取视频信息: {info_result.stderr[-300:]}"))
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

            # 下载视频
            dl_cmd = [
                "yt-dlp",
                "-f", "mp4/best[ext=mp4]/best",
                "--merge-output-format", "mp4",
                "--no-playlist",
                "-o", output_path,
                "--progress",
                "--newline",
                url,
            ]
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

    try:
        result = transcribe_video(video_path, provider=provider)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/translate", methods=["POST"])
def api_translate():
    """翻译句子"""
    data = request.get_json()
    segments = data.get("segments", [])
    source_lang = data.get("source_lang", "泰语")

    if not segments:
        return jsonify({"error": "缺少 segments 参数"}), 400

    try:
        translations = translate_segments(segments, source_lang)
        return jsonify({"translations": translations})
    except Exception as e:
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

    # 保存上传的音频
    audio_file = request.files["audio"]
    audio_path = os.path.join(UPLOAD_TMP, "recording.webm")
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
    app.run(debug=True, port=5000)
