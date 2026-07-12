"""
Segment（字幕句）领域模型。

这是整个项目最核心的数据结构，对应：
  - 转录结果中的每一句话
  - 前端 player.js 中的 segment 对象
  - 本地保存的字幕 JSON 中的每个元素

设计原则：
  - 只定义数据，不包含业务逻辑
  - from_json / to_json 保证 100% 兼容现有 JSON 格式
  - from_internal_dict 额外承担内部私有字段的清洗工作
"""


class Segment:
    """
    一个字幕句（Sentence）的完整数据。

    公开字段（to_json 输出、前端可见）：
      index        int     在视频中的序号（0-based）
      text         str     原文文本
      start        float   开始时间（秒）
      end          float   结束时间（秒）
      translation  str     译文（可选）
      romanization str     拼音 / 罗马拼音（中文/泰语，可选）
      confidence   float   置信度 0-1（可选，来自 combined 模式）
      source       str     识别来源 "groq"/"azure"（可选，来自 combined 模式）
      word_timings list    词级时间戳 [{start, end}, ...]（可选）
    """

    __slots__ = (
        "index", "text", "start", "end",
        "translation", "romanization",
        "confidence", "source", "word_timings",
    )

    def __init__(
        self,
        index: int,
        text: str,
        start: float,
        end: float,
        translation: str = "",
        romanization: str = "",
        confidence=None,
        source: str = "",
        word_timings=None,
    ):
        self.index = index
        self.text = text
        self.start = start
        self.end = end
        self.translation = translation
        self.romanization = romanization
        self.confidence = confidence
        self.source = source
        self.word_timings = word_timings if word_timings is not None else []

    # ── 构造 ────────────────────────────────────────────────────────

    @classmethod
    def from_json(cls, d: dict) -> "Segment":
        """从已存 JSON（字幕文件或 API 响应）构造。"""
        return cls(
            index=int(d.get("index", 0)),
            text=d.get("text", ""),
            start=float(d.get("start", 0)),
            end=float(d.get("end", 0)),
            translation=d.get("translation", ""),
            romanization=d.get("romanization", ""),
            confidence=d.get("confidence"),
            source=d.get("source", ""),
            word_timings=d.get("wordTimings", []),
        )

    @classmethod
    def from_internal_dict(cls, d: dict) -> "Segment":
        """从转录管道内部 dict（含 _conf / _confidence / _source 等私有字段）构造。

        同时完成字段清洗：私有字段重命名为公开字段，_logprob/_no_speech 丢弃。
        替代 app.py 里手动 pop/rename 的那段代码。
        """
        # _conf（combined 模式计算值）优先；其次 _confidence（纯 Azure 输出）
        raw_conf = d.get("_conf")
        if raw_conf is None:
            raw_conf = d.get("_confidence")
        conf = round(float(raw_conf), 2) if raw_conf is not None else None

        source = d.get("_source") or d.get("source") or ""

        return cls(
            index=int(d.get("index", 0)),
            text=d.get("text", ""),
            start=float(d.get("start", 0)),
            end=float(d.get("end", 0)),
            translation=d.get("translation", ""),
            romanization=d.get("romanization", ""),
            confidence=conf,
            source=source,
            word_timings=d.get("wordTimings", []),
        )

    # ── 序列化 ──────────────────────────────────────────────────────

    def to_json(self) -> dict:
        """序列化为 JSON dict，仅输出有值的可选字段，100% 兼容现有格式。"""
        d: dict = {
            "index": self.index,
            "text": self.text,
            "start": self.start,
            "end": self.end,
        }
        if self.translation:
            d["translation"] = self.translation
        if self.romanization:
            d["romanization"] = self.romanization
        if self.confidence is not None:
            d["confidence"] = self.confidence
        if self.source:
            d["source"] = self.source
        if self.word_timings:
            d["wordTimings"] = self.word_timings
        return d

    def __repr__(self) -> str:
        return (
            f"Segment(index={self.index}, start={self.start}, end={self.end}, "
            f"text={self.text!r})"
        )
