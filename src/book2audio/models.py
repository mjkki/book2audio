"""统一数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Chapter:
    """一本书的一个章节。

    - index: 从 1 开始的章节序号（由识别顺序决定）
    - title: 章节标题（原文，如“第一章 初遇”）
    - content: 清洗后的章节正文（纯文本）
    - kind: 章节类型，front/body/back（前言/正文/后部）
    """

    index: int
    title: str
    content: str
    kind: str = "body"

    @property
    def char_count(self) -> int:
        return len(self.content.strip())


@dataclass
class Book:
    """解析后的一本书。"""

    title: str
    source_path: str
    source_format: str
    chapters: list[Chapter] = field(default_factory=list)


@dataclass
class Segment:
    """章节内被切分为可独立合成的一段文本。"""

    text: str
    # 合成完成后填充
    audio_path: Optional[str] = None
    # 在章节音频中的起始时间（秒），合成完成后填充
    start_time: float = 0.0
    # 本段音频时长（秒）
    duration: float = 0.0


@dataclass
class ChapterResult:
    """一章的处理结果。"""

    chapter: Chapter
    status: str  # ok / failed / skipped
    mp3_path: Optional[str] = None
    lrc_path: Optional[str] = None
    json_path: Optional[str] = None
    duration: float = 0.0
    error: Optional[str] = None
