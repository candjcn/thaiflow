"""
发音评估领域模型。

来自 Azure Speech Pronunciation Assessment 的结果。
由 ai/pronunciation.py 返回，通过 /api/pronounce 发送给前端。
"""


class PronunciationWord:
    """单词级发音评估详情。"""

    __slots__ = ("word", "accuracy_score", "error_type")

    def __init__(self, word: str, accuracy_score: float = 0.0, error_type: str = "None"):
        self.word = word
        self.accuracy_score = accuracy_score
        self.error_type = error_type

    @classmethod
    def from_json(cls, d: dict) -> "PronunciationWord":
        return cls(
            word=d.get("word", ""),
            accuracy_score=float(d.get("accuracy_score", 0)),
            error_type=d.get("error_type", "None"),
        )

    def to_json(self) -> dict:
        return {
            "word": self.word,
            "accuracy_score": self.accuracy_score,
            "error_type": self.error_type,
        }

    def __repr__(self) -> str:
        return (
            f"PronunciationWord(word={self.word!r}, "
            f"accuracy={self.accuracy_score}, error={self.error_type!r})"
        )


class PronunciationResult:
    """
    整句发音评估结果。

    字段：
      recognized_text    str    Azure 实际识别到的文本
      overall_score      float  综合得分（0-100）
      accuracy_score     float  准确度（0-100）
      fluency_score      float  流利度（0-100）
      completeness_score float  完整度（0-100）
      words              list   每词评估详情
      error              str    识别失败时的错误信息（可选）
    """

    __slots__ = (
        "recognized_text", "overall_score", "accuracy_score",
        "fluency_score", "completeness_score", "words", "error",
    )

    def __init__(
        self,
        recognized_text: str = "",
        overall_score: float = 0.0,
        accuracy_score: float = 0.0,
        fluency_score: float = 0.0,
        completeness_score: float = 0.0,
        words=None,
        error: str = "",
    ):
        self.recognized_text = recognized_text
        self.overall_score = overall_score
        self.accuracy_score = accuracy_score
        self.fluency_score = fluency_score
        self.completeness_score = completeness_score
        self.words = words if words is not None else []
        self.error = error

    @classmethod
    def from_json(cls, d: dict) -> "PronunciationResult":
        words = [PronunciationWord.from_json(w) for w in d.get("words", [])]
        return cls(
            recognized_text=d.get("recognized_text", ""),
            overall_score=float(d.get("overall_score", 0)),
            accuracy_score=float(d.get("accuracy_score", 0)),
            fluency_score=float(d.get("fluency_score", 0)),
            completeness_score=float(d.get("completeness_score", 0)),
            words=words,
            error=d.get("error", ""),
        )

    def to_json(self) -> dict:
        d: dict = {
            "recognized_text": self.recognized_text,
            "overall_score": self.overall_score,
            "accuracy_score": self.accuracy_score,
            "fluency_score": self.fluency_score,
            "completeness_score": self.completeness_score,
            "words": [w.to_json() for w in self.words],
        }
        if self.error:
            d["error"] = self.error
        return d

    def __repr__(self) -> str:
        return (
            f"PronunciationResult(overall={self.overall_score}, "
            f"accuracy={self.accuracy_score}, words={len(self.words)})"
        )
