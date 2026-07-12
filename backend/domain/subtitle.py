"""
SubtitleFile 领域模型。

对应保存到本地的字幕 JSON 文件格式：
  {"segments": [...], "language": "th", "cover": "xxx.jpg"}

这是视频 / 课程数据在磁盘上的完整表示。
播放器加载、导出 SRT、烧录字幕都从这里读取数据。
"""

from .segment import Segment


class SubtitleFile:
    """
    字幕文件的完整数据结构。

    字段：
      segments  list[Segment]  所有字幕句
      language  str            ISO 2-letter 语言代码（"th" / "zh" / "en" 等）
      cover     str            封面图文件名（TTS 课程专用，可选）
    """

    __slots__ = ("segments", "language", "cover")

    def __init__(self, segments, language: str, cover: str = ""):
        self.segments = segments   # list[Segment]
        self.language = language
        self.cover = cover

    # ── 构造 ────────────────────────────────────────────────────────

    @classmethod
    def from_json(cls, d: dict) -> "SubtitleFile":
        """从字幕 JSON 文件（或 API 响应 dict）构造。"""
        segs = [Segment.from_json(s) for s in d.get("segments", [])]
        return cls(
            segments=segs,
            language=d.get("language", ""),
            cover=d.get("cover", ""),
        )

    # ── 序列化 ──────────────────────────────────────────────────────

    def to_json(self) -> dict:
        """序列化，与现有磁盘 JSON 格式 100% 兼容。"""
        d: dict = {
            "segments": [s.to_json() for s in self.segments],
            "language": self.language,
        }
        if self.cover:
            d["cover"] = self.cover
        return d

    def __repr__(self) -> str:
        return (
            f"SubtitleFile(language={self.language!r}, "
            f"segments={len(self.segments)}, cover={self.cover!r})"
        )
