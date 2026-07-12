"""
Word（词级时间戳）领域模型。

来源：Groq / OpenAI Whisper 的 word-granularity 输出。
经 align_word_timestamps() 对齐后存入 Segment.word_timings，
格式精简为 {start, end}（text 不重复存储，由 Segment.text 分词得到）。

本模型表示完整的词对象，含 text，用于展示和分析场景。
"""


class Word:
    """单词及其时间信息。"""

    __slots__ = ("text", "start", "end")

    def __init__(self, text: str, start: float, end: float):
        self.text = text
        self.start = start
        self.end = end

    @classmethod
    def from_json(cls, d: dict) -> "Word":
        # 兼容 {"word": ...} 和 {"text": ...} 两种键名
        return cls(
            text=d.get("word", d.get("text", "")),
            start=float(d.get("start", 0)),
            end=float(d.get("end", 0)),
        )

    def to_json(self) -> dict:
        return {"word": self.text, "start": self.start, "end": self.end}

    def __repr__(self) -> str:
        return f"Word(text={self.text!r}, start={self.start}, end={self.end})"
