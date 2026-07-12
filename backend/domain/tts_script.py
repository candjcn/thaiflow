"""
TTSSentence 领域模型。

Gemini TTS 脚本中每一句的数据结构。
由 ai/tts.py 的 prepare_script() 生成，
包含朗读所需的完整标注：说话人、性别、情感。
"""


class TTSSentence:
    """
    TTS 脚本中的单句。

    字段：
      text     str  朗读文本
      speaker  str  说话人标识："A" / "B" / "N"（旁白）
      gender   str  说话人性别："male" / "female"
      emotion  str  情感描述，用于 TTS 提示词（如 "warm storytelling"）
    """

    __slots__ = ("text", "speaker", "gender", "emotion")

    def __init__(
        self,
        text: str,
        speaker: str = "N",
        gender: str = "female",
        emotion: str = "natural",
    ):
        self.text = text
        self.speaker = speaker
        self.gender = gender
        self.emotion = emotion

    @classmethod
    def from_json(cls, d: dict) -> "TTSSentence":
        return cls(
            text=d.get("text", ""),
            speaker=d.get("speaker", "N"),
            gender=d.get("gender", "female"),
            emotion=d.get("emotion", "natural"),
        )

    def to_json(self) -> dict:
        return {
            "text": self.text,
            "speaker": self.speaker,
            "gender": self.gender,
            "emotion": self.emotion,
        }

    def __repr__(self) -> str:
        return (
            f"TTSSentence(speaker={self.speaker!r}, gender={self.gender!r}, "
            f"emotion={self.emotion!r}, text={self.text!r})"
        )
