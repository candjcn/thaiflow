"""
WordDefinition 领域模型。

单词释义查询结果（来自 DeepSeek / Gemini 词典功能）。
通过 /api/word-define 返回给前端。
"""


class WordDefinition:
    """
    单词释义。

    字段：
      meaning  str  简短含义（≤15 字符）
      pos      str  词性缩写（"n." / "v." / "adj." / "adv." 等）
    """

    __slots__ = ("meaning", "pos")

    def __init__(self, meaning: str = "", pos: str = ""):
        self.meaning = meaning
        self.pos = pos

    @classmethod
    def from_json(cls, d: dict) -> "WordDefinition":
        return cls(meaning=d.get("meaning", ""), pos=d.get("pos", ""))

    def to_json(self) -> dict:
        return {"meaning": self.meaning, "pos": self.pos}

    def __repr__(self) -> str:
        return f"WordDefinition(pos={self.pos!r}, meaning={self.meaning!r})"
