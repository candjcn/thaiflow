#!/usr/bin/env python3
"""
泰语 ASR 标准集评测脚本。

用途：
  1) 自动配对视频与标准 .srt
  2) 跑多条链路：
       - groq
       - openai_whisper
       - current_mix (gpt-4o-transcribe + groq projection)
       - qwen (qwen3-asr-flash-filetrans)
  3) 与 ground truth 做文本级对比
  4) 输出 JSON 和 Markdown 报告

默认会递归扫描视频目录，并按同名 .srt 配对。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Optional


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai import speech  # noqa: E402
from ai.provider import openai_whisper as openai_provider  # noqa: E402


VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}


@dataclass
class SampleResult:
    ok: bool
    time: float
    segments: int = 0
    chars: int = 0
    sim: float = 0.0
    cer: float = 0.0
    error: str = ""
    first: list | None = None


def load_env() -> None:
    env_path = BACKEND_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Thai ASR ground-truth evaluator")
    parser.add_argument(
        "data_dir",
        nargs="?",
        default="/Users/apple/Movies/泰语吐槽系列视频",
        help="Root directory containing videos and matching .srt files",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=0.0,
        help="Skip videos longer than this many seconds; 0 means no limit",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only evaluate the first N matched pairs; 0 means all",
    )
    parser.add_argument(
        "--json-out",
        default="",
        help="Write JSON report to this path",
    )
    parser.add_argument(
        "--md-out",
        default="",
        help="Write Markdown report to this path",
    )
    parser.add_argument(
        "--skip-openai-whisper",
        action="store_true",
        help="Skip the old whisper-1 comparison path",
    )
    parser.add_argument(
        "--skip-current-mix",
        action="store_true",
        help="Skip the current gpt-4o-transcribe + groq comparison path",
    )
    parser.add_argument(
        "--skip-qwen",
        action="store_true",
        help="Skip the qwen3-asr-flash-filetrans comparison path",
    )
    return parser.parse_args()


def parse_srt(path: Path) -> list[dict]:
    txt = path.read_text(encoding="utf-8", errors="ignore").replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", txt.strip()):
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        m = re.match(
            r"(\d\d):(\d\d):(\d\d)[,\.]?(\d\d\d)\s*-->\s*(\d\d):(\d\d):(\d\d)[,\.]?(\d\d\d)",
            lines[1],
        )
        if not m:
            continue
        sh, sm, ss, sms, eh, em, es, ems = m.groups()
        cues.append(
            {
                "start": int(sh) * 3600 + int(sm) * 60 + int(ss) + int(sms) / 1000,
                "end": int(eh) * 3600 + int(em) * 60 + int(es) + int(ems) / 1000,
                "text": " ".join(lines[2:]).strip(),
            }
        )
    return cues


def normalize_text(text: str) -> str:
    out = []
    for ch in (text or "").lower():
        cat = unicodedata.category(ch)
        if cat.startswith(("L", "N")) or ("\u0e00" <= ch <= "\u0e7f") or ("\u4e00" <= ch <= "\u9fff") or ("\u3040" <= ch <= "\u30ff"):
            out.append(ch)
    return "".join(out)


def similarity(a: str, b: str) -> float:
    na = normalize_text(a)
    nb = normalize_text(b)
    if not na and not nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def cer(a: str, b: str) -> float:
    na = normalize_text(a)
    nb = normalize_text(b)
    if not nb:
        return 0.0 if not na else 1.0
    if not na:
        return 1.0
    prev = list(range(len(nb) + 1))
    for i, ch1 in enumerate(na, 1):
        cur = [i] + [0] * len(nb)
        for j, ch2 in enumerate(nb, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ch1 != ch2))
        prev = cur
    return prev[-1] / max(1, len(nb))


def concat_segments(result: dict) -> str:
    return "".join(seg.get("text", "") for seg in result.get("segments", []))


def duration_seconds(path: Path) -> float:
    import subprocess

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return 0.0
    try:
        data = json.loads(proc.stdout or "{}")
        return float(data.get("format", {}).get("duration", 0.0) or 0.0)
    except Exception:
        return 0.0


def collect_pairs(data_dir: Path, max_duration: float, limit: int) -> list[tuple[Path, Path, float]]:
    subtitles = list(data_dir.rglob("*.srt"))
    pairs: list[tuple[Path, Path, float]] = []
    for video in data_dir.rglob("*"):
        if not video.is_file() or video.suffix.lower() not in VIDEO_EXTS:
            continue
        candidates = [s for s in subtitles if s.stem == video.stem and s.parent == video.parent]
        if not candidates:
            candidates = [s for s in subtitles if s.stem == video.stem]
        if not candidates:
            continue
        dur = duration_seconds(video)
        if max_duration > 0 and dur > max_duration:
            continue
        pairs.append((video, candidates[0], dur))

    # 去重：同一个字幕只保留第一次匹配
    uniq = []
    seen = set()
    for video, sub, dur in pairs:
        key = sub.resolve()
        if key in seen:
            continue
        seen.add(key)
        uniq.append((video, sub, dur))
    if limit > 0:
        uniq = uniq[:limit]
    return uniq


def run_provider(video: Path, provider: str, model: Optional[str] = None) -> tuple[SampleResult, dict | None]:
    orig_model = openai_provider.providers.OpenAI.TRANSCRIBE_MODEL
    orig_retry = speech._retry_low_confidence_with_groq
    try:
        if provider == "openai_whisper":
            openai_provider.providers.OpenAI.TRANSCRIBE_MODEL = model or "whisper-1"
            speech._retry_low_confidence_with_groq = lambda *args, **kwargs: None
            run_provider_name = "openai"
        elif provider == "current_mix":
            openai_provider.providers.OpenAI.TRANSCRIBE_MODEL = model or "gpt-4o-transcribe"
            speech._retry_low_confidence_with_groq = orig_retry
            run_provider_name = "openai"
        elif provider == "qwen":
            openai_provider.providers.OpenAI.TRANSCRIBE_MODEL = orig_model
            speech._retry_low_confidence_with_groq = orig_retry
            run_provider_name = "qwen"
        else:
            run_provider_name = "groq"
            openai_provider.providers.OpenAI.TRANSCRIBE_MODEL = orig_model
            speech._retry_low_confidence_with_groq = orig_retry

        started = time.time()
        result = speech.transcribe_video(str(video), provider=run_provider_name)
        elapsed = round(time.time() - started, 2)
        text = concat_segments(result)
        sample = SampleResult(
            ok=True,
            time=elapsed,
            segments=len(result.get("segments", [])),
            chars=len(text),
            first=(result.get("segments", [])[:4]),
        )
        return sample, result
    except Exception as exc:
        elapsed = round(time.time() - started, 2) if "started" in locals() else 0.0
        return SampleResult(ok=False, time=elapsed, error=str(exc)), None
    finally:
        openai_provider.providers.OpenAI.TRANSCRIBE_MODEL = orig_model
        speech._retry_low_confidence_with_groq = orig_retry


def render_markdown(report: dict) -> str:
    lines = []
    lines.append("# 泰语 ASR 标准集评测报告")
    lines.append("")
    lines.append("## 汇总")
    lines.append("")
    lines.append("| 方法 | 样本数 | 平均相似度 | 平均CER | 平均耗时(s) | 平均segments |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for method, agg in report.get("agg", {}).items():
        lines.append(
            f"| {method} | {agg['n']} | {agg['avg_sim']:.4f} | {agg['avg_cer']:.4f} | {agg['avg_time']:.2f} | {agg['avg_segments']:.2f} |"
        )
    lines.append("")
    lines.append("## 样本明细")
    lines.append("")
    for item in report.get("pairs", []):
        lines.append(f"### {Path(item['video']).name}")
        lines.append("")
        lines.append(f"- 视频：`{item['video']}`")
        lines.append(f"- 标准字幕：`{item['subtitle']}`")
        lines.append(f"- 标准 cue 数：{item['gt']['cues']}，标准字符数：{item['gt']['chars']}")
        for method in ["groq", "openai_whisper", "current_mix", "qwen"]:
            m = item.get(method)
            if not m:
                continue
            if m["ok"]:
                lines.append(
                    f"- {method}：相似度 {m['sim']:.4f}，CER {m['cer']:.4f}，耗时 {m['time']:.2f}s，segments {m['segments']}"
                )
            else:
                lines.append(f"- {method}：失败，耗时 {m['time']:.2f}s，错误：{m['error']}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    load_env()
    args = parse_args()
    data_dir = Path(args.data_dir).expanduser().resolve()

    pairs = collect_pairs(data_dir, args.max_duration, args.limit)
    if not pairs:
        print(f"没有在 {data_dir} 找到可配对的视频/字幕样本。", file=sys.stderr)
        return 1

    print(f"发现 {len(pairs)} 个样本对")
    for video, sub, dur in pairs:
        print(f"- {video.relative_to(data_dir)} -> {sub.relative_to(data_dir)} ({dur:.1f}s)")

    report = {"data_dir": str(data_dir), "pairs": [], "agg": {}}
    methods = ["groq"]
    if not args.skip_openai_whisper:
        methods.append("openai_whisper")
    if not args.skip_current_mix:
        methods.append("current_mix")
    if not args.skip_qwen:
        methods.append("qwen")

    orig_model = openai_provider.providers.OpenAI.TRANSCRIBE_MODEL
    orig_retry = speech._retry_low_confidence_with_groq
    try:
        for idx, (video, sub, dur) in enumerate(pairs, 1):
            gt_cues = parse_srt(sub)
            gt_text = "".join(c["text"] for c in gt_cues)
            print(f"\n[{idx}/{len(pairs)}] {video.name}  (ground truth cues={len(gt_cues)}, chars={len(gt_text)})")
            item = {
                "video": str(video),
                "subtitle": str(sub),
                "duration": dur,
                "gt": {"cues": len(gt_cues), "chars": len(gt_text)},
            }

            for method in methods:
                if method == "groq":
                    sample, result = run_provider(video, "groq")
                elif method == "openai_whisper":
                    sample, result = run_provider(video, "openai_whisper", model="whisper-1")
                elif method == "current_mix":
                    sample, result = run_provider(video, "current_mix", model="gpt-4o-transcribe")
                else:
                    sample, result = run_provider(video, "qwen")

                if sample.ok and result is not None:
                    text = concat_segments(result)
                    sample.sim = round(similarity(text, gt_text), 4)
                    sample.cer = round(cer(text, gt_text), 4)
                item[method] = asdict(sample)

                if sample.ok:
                    print(
                        f"  {method}: sim={sample.sim:.4f} cer={sample.cer:.4f} "
                        f"time={sample.time:.2f}s segs={sample.segments}"
                    )
                else:
                    print(f"  {method}: FAIL time={sample.time:.2f}s err={sample.error}")

            report["pairs"].append(item)

    finally:
        openai_provider.providers.OpenAI.TRANSCRIBE_MODEL = orig_model
        speech._retry_low_confidence_with_groq = orig_retry

    for method in methods:
        vals = [r[method] for r in report["pairs"] if r.get(method, {}).get("ok")]
        if not vals:
            continue
        report["agg"][method] = {
            "n": len(vals),
            "avg_sim": round(sum(v["sim"] for v in vals) / len(vals), 4),
            "avg_cer": round(sum(v["cer"] for v in vals) / len(vals), 4),
            "avg_time": round(sum(v["time"] for v in vals) / len(vals), 2),
            "avg_segments": round(sum(v["segments"] for v in vals) / len(vals), 2),
        }

    print("\n== 汇总 ==")
    for method, agg in report["agg"].items():
        print(
            f"{method}: n={agg['n']} avg_sim={agg['avg_sim']:.4f} "
            f"avg_cer={agg['avg_cer']:.4f} avg_time={agg['avg_time']:.2f}s "
            f"avg_segments={agg['avg_segments']:.2f}"
        )

    json_text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out:
        Path(args.json_out).expanduser().resolve().write_text(json_text, encoding="utf-8")
        print(f"\nJSON report saved to {args.json_out}")
    else:
        print("\nJSON report:")
        print(json_text[:2000])

    md_text = render_markdown(report)
    if args.md_out:
        Path(args.md_out).expanduser().resolve().write_text(md_text, encoding="utf-8")
        print(f"Markdown report saved to {args.md_out}")
    else:
        print("\nMarkdown report preview:")
        print(md_text[:2000])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
