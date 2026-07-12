"""
ReelSpeak 统一领域模型（Domain Model）。

所有数据结构的唯一定义来源。
业务模块通过 `from domain import Segment, SubtitleFile, ...` 引用。

核心对象：
  Segment          字幕句（最核心，贯穿转录 / 翻译 / 导出 / 播放）
  SubtitleFile     字幕文件容器（segments + language + cover）
  Word             词级时间戳
  TTSSentence      TTS 脚本中的单句（text + speaker + gender + emotion）
  PronunciationResult  发音评估结果
  PronunciationWord    发音评估中单词级详情
  WordDefinition   单词释义查询结果

设计约束：
  - 只定义数据，不包含 AI / HTTP / 数据库逻辑
  - from_json() / to_json() 保证 100% 兼容现有 JSON 格式
  - 纯 Python，不依赖任何第三方库
"""

from .segment import Segment
from .subtitle import SubtitleFile
from .word import Word
from .tts_script import TTSSentence
from .pronunciation import PronunciationResult, PronunciationWord
from .definition import WordDefinition

__all__ = [
    "Segment",
    "SubtitleFile",
    "Word",
    "TTSSentence",
    "PronunciationResult",
    "PronunciationWord",
    "WordDefinition",
]
