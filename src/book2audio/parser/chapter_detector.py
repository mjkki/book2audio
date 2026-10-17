"""章节识别：从整本文本流中切分出章节。

策略：
1. 用可配置的正则识别“章节标题行”
2. 过滤目录页：开头的连续标题行（后面没有正文）会被识别为目录并丢弃
3. 第一个章节标题之前的内容作为“前言/序”章节（非空时保留）
4. 支持中英文常见标题格式
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from ..models import Chapter

logger = logging.getLogger("book2audio.parser.chapter_detector")

# 章节标题行的最大长度，避免把正文长行误判为标题
_MAX_TITLE_LEN = 60
# 连续标题行判为目录的最小数量
_TOC_MIN_CONSECUTIVE = 3
# 一个标题行后面跟的正文最少字符数，若低于该值则整段可能属于目录
_MIN_BODY_CHARS = 12


@dataclass
class ChapterDetector:
    patterns: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._compiled = [re.compile(p) for p in self.patterns]

    def is_title_line(self, line: str) -> bool:
        """判断一行是否为章节标题行。"""
        stripped = line.strip()
        if not stripped:
            return False
        matched = any(p.match(stripped) for p in self._compiled)
        if not matched:
            return False
        if len(stripped) > _MAX_TITLE_LEN:
            # 正则命中但超长：告警而非静默丢弃，便于排查「正则不生效」
            logger.warning(
                "疑似章节标题超过 %d 字被丢弃：%s...（如确认是标题，请缩短该行或调整正则）",
                _MAX_TITLE_LEN,
                stripped[:30],
            )
            return False
        # 数字编号格式（如 "1. xxx"）可能是正文列表项/脚注：仅当行很短且无句号结尾时才视为标题
        # 避免把正文中的编号列表行（"1. 现代集团..."）或脚注（"1. 美国俄亥俄州。——译者注"）
        # 误判为章节标题而吞掉内容
        if re.match(r"^\d+[.、]\s*\S", stripped):
            if len(stripped) > 20:
                return False
            # 句号/译者注结尾 -> 脚注或完整句子，不是标题
            if re.search(r"[。！？!?]$", stripped) or "译者注" in stripped:
                return False
        return True

    def split(self, raw_text: str) -> list[Chapter]:
        """将整本文本拆分为章节列表。"""
        lines = raw_text.split("\n")
        n = len(lines)
        # 找出所有标题行
        title_idx = [i for i, ln in enumerate(lines) if self.is_title_line(ln)]
        if not title_idx:
            # 全书无标题：整体作为一章
            content = "\n".join(l for l in lines if l.strip()).strip()
            return [Chapter(index=1, title="全书", content=content)] if content else []

        # 过滤目录：开头连续标题行（其后直到下一个标题行之间正文过少）
        title_idx = self._drop_toc_lines(lines, title_idx)

        # 用标题行切分
        chapters: list[Chapter] = []
        body_start = 0
        # 第一个标题之前的前言内容
        front_content = "\n".join(l for l in lines[: title_idx[0]] if l.strip()).strip()
        if front_content:
            chapters.append(Chapter(index=len(chapters) + 1, title="前言", content=front_content, kind="front"))

        for pos, idx in enumerate(title_idx):
            end = title_idx[pos + 1] if pos + 1 < len(title_idx) else n
            title = lines[idx].strip()
            body = "\n".join(l for l in lines[idx + 1 : end] if l.strip()).strip()
            chapters.append(Chapter(index=len(chapters) + 1, title=title, content=body))

        return [c for c in chapters if c.content.strip()]

    def _drop_toc_lines(self, lines: list[str], title_idx: list[int]) -> list[int]:
        """丢弃位于开头、内容过少的连续标题行（目录页）。"""
        if len(title_idx) < _TOC_MIN_CONSECUTIVE:
            return title_idx
        drop = 0
        for pos, idx in enumerate(title_idx[:-1]):
            next_idx = title_idx[pos + 1]
            body = "".join(lines[idx + 1 : next_idx])
            if len(body.strip()) <= _MIN_BODY_CHARS:
                drop += 1
                continue
            break
        if drop:
            return title_idx[drop:]
        return title_idx
