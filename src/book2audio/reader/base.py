"""读取器基类与工厂。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..models import Book
from ..parser.chapter_detector import ChapterDetector
from ..parser.text_cleaner import clean_text


class BaseReader:
    """所有读取器的公共基类。

    提供章节识别（复用 ChapterDetector）与清洗能力，
    子类只需实现 _read_raw() 返回原始文本。
    """

    def __init__(self, patterns: Optional[list[str]] = None):
        self.detector = ChapterDetector(patterns or [])

    def _read_raw(self, path: Path) -> str:  # pragma: no cover - 子类实现
        raise NotImplementedError

    def read(self, path: str | Path, book_title: Optional[str] = None) -> Book:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"图书文件不存在: {p}")
        raw = self._read_raw(p)
        cleaned = clean_text(raw)
        if not cleaned:
            raise ValueError(f"图书内容为空或无法解析: {p}")
        chapters = self.detector.split(cleaned)
        title = book_title or self._default_title(p)
        return Book(title=title, source_path=str(p), source_format=p.suffix.lstrip(".").lower(), chapters=chapters)

    @staticmethod
    def _default_title(path: Path) -> str:
        return path.stem


def reader_for_format(fmt: str, patterns: Optional[list[str]] = None) -> BaseReader:
    """按扩展名返回对应读取器。"""
    from .txt_reader import TxtReader
    from .epub_reader import EpubReader
    from .mobi_reader import MobiReader

    fmt = fmt.lower().lstrip(".")
    if fmt in ("txt", "text", "md", "markdown"):
        return TxtReader(patterns)
    if fmt == "epub":
        return EpubReader(patterns)
    if fmt in ("mobi", "azw", "azw3"):
        return MobiReader(patterns)
    raise ValueError(f"暂不支持的图书格式: .{fmt}（支持 txt / epub / mobi）")
