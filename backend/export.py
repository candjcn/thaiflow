import os
import json
import re
import subprocess
import unicodedata
from config import settings


def format_drawtext_time(seconds):
    """将秒数转为 ffmpeg 可比较的秒数字符串"""
    return f"{seconds:.2f}"


def format_srt_time(seconds):
    """将秒数转为 SRT 时间格式 HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def escape_drawtext(text):
    """转义 drawtext 滤镜中的特殊字符"""
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "'\\''")
    text = text.replace(":", "\\:")
    text = text.replace("%", "%%")
    text = text.replace("\n", " ")
    return text


def get_video_info(video_path):
    """用 ffprobe 获取视频分辨率和时长"""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    info = json.loads(result.stdout)
    stream = info["streams"][0]
    duration = float(info["format"]["duration"])
    return stream["width"], stream["height"], duration


def find_font():
    """查找系统中同时支持泰文和中文的字体"""
    for f in settings.FONT_SEARCH_PATHS:
        if os.path.exists(f):
            return f
    return "Arial"


# ========== 泰文相关工具 ==========

# 泰文组合字符：元音上/下标、声调符号等（不占独立宽度，不能作为断行点）
# 0E31: สระอะ上标, 0E34-0E3A: สระอิ系列上/下标, 0E47-0E4E: 声调/其他上标
THAI_COMBINING = (
    {0x0E31}
    | set(range(0x0E34, 0x0E3B))
    | set(range(0x0E47, 0x0E4F))
)


def is_thai(ch):
    return '\u0e00' <= ch <= '\u0e7f'


def is_thai_combining(ch):
    return ord(ch) in THAI_COMBINING


def is_cjk(ch):
    return '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u30ff' or '\uff00' <= ch <= '\uffef'


def char_width(ch, font_size):
    """估算单个字符的渲染宽度（偏保守，宁可早换行也不超出）"""
    if is_thai_combining(ch):
        return 0  # 组合字符叠在基础字符上，不占额外宽度
    if is_thai(ch):
        return font_size * 0.55  # 泰文基础字符宽度接近拉丁字母
    if is_cjk(ch):
        return font_size * 0.95
    if ch in (' ',):
        return font_size * 0.3
    if unicodedata.east_asian_width(ch) in ('W', 'F'):
        return font_size * 0.95
    return font_size * 0.55


def split_thai_tokens(text):
    """
    将泰文文本拆成可断行的小 token。
    泰文没有空格分词，这里在以下位置允许断行：
    - 空格前后
    - 泰文特殊字符（ๆ、ฯ）之后
    - 当一个基础辅音跟在另一个基础辅音后面时（前一个辅音没有元音组合，
      通常意味着是一个新音节的开始，可以作为断行候选点）
    """
    tokens = []
    current = ""

    i = 0
    while i < len(text):
        ch = text[i]

        if ch == ' ':
            if current:
                tokens.append(current)
                current = ""
            tokens.append(' ')
            i += 1
            continue

        current += ch

        # ๆ (0E46) 和 ฯ (0E2F) 后面可以断行
        if ch in ('ๆ', 'ฯ'):
            tokens.append(current)
            current = ""
            i += 1
            continue

        # 检查是否可以在下一个基础辅音前断行
        # 条件：当前字符是泰文，下一个非组合泰文字符是基础辅音，
        # 且当前 token 已经有至少 3 个基础辅音（避免拆得太碎）
        if is_thai(ch) and not is_thai_combining(ch):
            # 往后看：跳过组合字符，看下一个基础字符
            j = i + 1
            while j < len(text) and is_thai_combining(text[j]):
                current += text[j]
                j += 1
            # 如果下一个字符也是泰文基础辅音，且当前 token 够长，可以断
            base_count = sum(1 for c in current if is_thai(c) and not is_thai_combining(c))
            if (j < len(text) and is_thai(text[j]) and not is_thai_combining(text[j])
                    and base_count >= 3):
                tokens.append(current)
                current = ""
            i = j
            continue

        i += 1

    if current:
        tokens.append(current)
    return tokens


def tokenize_for_wrap(text):
    """
    将文本分割为可断行的 token 列表。
    - 泰文：按音节/短词拆分，允许在合理位置断行
    - 中文：每个字符可独立断行
    - 英文/数字：连续的字母数字作为一个 token
    - 空格：独立 token
    """
    tokens = []
    current = ""
    current_type = None

    def flush():
        nonlocal current, current_type
        if current:
            if current_type == "thai":
                tokens.extend(split_thai_tokens(current))
            else:
                tokens.append(current)
            current = ""
            current_type = None

    for ch in text:
        if ch == ' ':
            flush()
            tokens.append(' ')
            continue

        if is_thai(ch) or is_thai_combining(ch):
            ch_type = "thai"
        elif is_cjk(ch):
            ch_type = "cjk"
        elif ch.isalnum() or ch in ('-', '_'):
            ch_type = "latin"
        else:
            ch_type = "other"

        if ch_type == "cjk":
            flush()
            tokens.append(ch)
            continue

        if ch_type in ("thai", "latin"):
            if current_type == ch_type:
                current += ch
            else:
                flush()
                current = ch
                current_type = ch_type
            continue

        flush()
        tokens.append(ch)

    flush()
    return tokens


def token_width(token, font_size):
    """计算一个 token 的渲染宽度"""
    return sum(char_width(ch, font_size) for ch in token)


def force_break_token(token, font_size, max_width):
    """
    当单个 token 超过 max_width 时，强制按字符断行。
    在非组合字符位置断开，不把组合字符和基础字符拆开。
    """
    lines = []
    current = ""
    current_w = 0

    i = 0
    while i < len(token):
        ch = token[i]
        cw = char_width(ch, font_size)

        # 收集这个字符和后续的组合字符
        cluster = ch
        cluster_w = cw
        j = i + 1
        while j < len(token) and is_thai_combining(token[j]):
            cluster += token[j]
            cluster_w += char_width(token[j], font_size)
            j += 1

        if current_w + cluster_w > max_width and current:
            lines.append(current)
            current = cluster
            current_w = cluster_w
        else:
            current += cluster
            current_w += cluster_w

        i = j

    if current:
        lines.append(current)
    return lines


def wrap_text(text, font_size, max_width):
    """
    智能折行：按 token 断行。
    如果单个 token 超过 max_width，强制按字符断开。
    """
    tokens = tokenize_for_wrap(text)
    lines = []
    current_line = ""
    current_width = 0

    for tk in tokens:
        tk_w = token_width(tk, font_size)

        if tk == ' ' and not current_line:
            continue

        # 单个 token 就超过最大宽度 → 强制断行
        if tk_w > max_width:
            if current_line:
                lines.append(current_line.rstrip())
                current_line = ""
                current_width = 0
            broken = force_break_token(tk, font_size, max_width)
            for part in broken[:-1]:
                lines.append(part)
            current_line = broken[-1] if broken else ""
            current_width = token_width(current_line, font_size)
            continue

        if current_width + tk_w > max_width and current_line:
            lines.append(current_line.rstrip())
            current_line = "" if tk == ' ' else tk
            current_width = 0 if tk == ' ' else tk_w
        else:
            current_line += tk
            current_width += tk_w

    if current_line.strip():
        lines.append(current_line.rstrip())

    return lines


# ========== SRT 导出 ==========

def generate_srt_single(segments, field):
    """生成单语 SRT 字幕，field 为 'text' 或 'translation'（接受 Segment 对象列表）"""
    lines = []
    seq = 0
    for seg in segments:
        content = getattr(seg, field, "").strip()
        if not content:
            continue
        seq += 1
        lines.append(f"{seq}")
        lines.append(f"{format_srt_time(seg.start)} --> {format_srt_time(seg.end)}")
        lines.append(content)
        lines.append("")
    return "\n".join(lines)


def export_srt(subtitle_file, export_dir, base_name, language=None):
    """导出两个独立的 SRT 字幕文件，返回文件名列表。

    Args:
        subtitle_file: SubtitleFile 对象
        export_dir:    导出目录
        base_name:     文件名前缀
        language:      语言代码（省略时从 subtitle_file.language 读取）
    """
    lang = (language or subtitle_file.language or "")[:2]
    lang_label = {
        "th": "泰语", "en": "英语", "ja": "日语", "ko": "韩语",
        "zh": "中文", "fr": "法语", "de": "德语", "es": "西班牙语",
        "pt": "葡萄牙语", "ru": "俄语", "it": "意大利语", "vi": "越南语",
        "hi": "印地语", "ar": "阿拉伯语",
    }
    orig_label = lang_label.get(lang, "原文")

    orig_name = f"{base_name}_{orig_label}.srt"
    zh_name = f"{base_name}_中文.srt"

    with open(os.path.join(export_dir, orig_name), "w", encoding="utf-8") as f:
        f.write(generate_srt_single(subtitle_file.segments, "text"))
    with open(os.path.join(export_dir, zh_name), "w", encoding="utf-8") as f:
        f.write(generate_srt_single(subtitle_file.segments, "translation"))

    return [orig_name, zh_name]


# ========== 视频导出 ==========

def build_drawtext_filter(segments, video_width, video_height, font_path):
    """为每句构建 drawtext 滤镜链：原文金色在上，中文白色在下，底部显示，带背景"""
    if video_width > video_height:
        font_size_orig = max(20, video_height // 18)
        font_size_trans = max(16, video_height // 22)
    else:
        font_size_orig = max(18, video_width // 22)
        font_size_trans = max(14, video_width // 28)

    # 字幕最大宽度：视频宽度的 75%
    max_sub_width = video_width * 0.75

    # 行高 = 字号 * 行距系数 + 背景框上下内边距，避免行间背景框重叠
    thai_line_height = int(font_size_orig * 1.4) + 2 * 8
    trans_line_height = int(font_size_trans * 1.25) + 2 * 8
    line_gap = 2             # 同语种行间距
    block_gap = 4            # 原文与翻译之间间距
    block_padding = 8        # 背景框内边距
    bottom_margin = 20       # 距视频底部

    filters = []
    for seg in segments:
        start = format_drawtext_time(seg.start)
        end = format_drawtext_time(seg.end)
        text = seg.text.strip()
        translation = seg.translation.strip()

        orig_lines = wrap_text(text, font_size_orig, max_sub_width) if text else []
        trans_lines = wrap_text(translation, font_size_trans, max_sub_width) if translation else []

        # 从底部往上排列
        all_draws = []
        y_cursor = video_height - bottom_margin

        # 翻译行（从最后一行往上排）
        for line in reversed(trans_lines):
            y_cursor -= trans_line_height
            escaped = escape_drawtext(line)
            all_draws.append((escaped, font_size_trans, "white", y_cursor))
            y_cursor -= line_gap

        if orig_lines and trans_lines:
            y_cursor -= block_gap

        # 原文行（从最后一行往上排）
        for line in reversed(orig_lines):
            y_cursor -= thai_line_height
            escaped = escape_drawtext(line)
            all_draws.append((escaped, font_size_orig, "gold", y_cursor))
            y_cursor -= line_gap

        for escaped_text, fsize, color, y in all_draws:
            f = (
                f"drawtext=fontfile='{font_path}'"
                f":text='{escaped_text}'"
                f":fontsize={fsize}"
                f":fontcolor={color}"
                f":borderw=2"
                f":bordercolor=black"
                f":box=1"
                f":boxcolor=black@0.5"
                f":boxborderw={block_padding}"
                f":x=(w-text_w)/2"
                f":y={y}"
                f":enable='between(t,{start},{end})'"
            )
            filters.append(f)

    return ",".join(filters)


def export_video_with_subtitles(video_path, subtitle_file, output_path, progress_callback=None):
    """将双语字幕烧录进视频。

    Args:
        subtitle_file: SubtitleFile 对象
    """
    width, height, duration = get_video_info(video_path)
    font_path = find_font()

    vf = build_drawtext_filter(subtitle_file.segments, width, height, font_path)
    if not vf:
        raise RuntimeError("没有字幕内容可烧录")

    cmd = [
        "ffmpeg", "-y",
        "-progress", "pipe:1",
        "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )

    time_pattern = re.compile(r"out_time_ms=(\d+)")
    while True:
        line = process.stdout.readline()
        if not line:
            break
        match = time_pattern.search(line)
        if match and duration > 0 and progress_callback:
            current_us = int(match.group(1))
            current_s = current_us / 1_000_000
            pct = min(99, int(current_s / duration * 100))
            progress_callback(pct)

    process.wait()
    if process.returncode != 0:
        stderr = process.stderr.read()
        raise RuntimeError(f"ffmpeg 失败: {stderr[-500:]}")

    if progress_callback:
        progress_callback(100)

    return output_path
