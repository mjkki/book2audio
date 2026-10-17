"""mobi 读取器。

通过 mobi 库解包：
- 老 mobi (mobi7) 返回 HTML 文件 -> 提取文本后走统一章节识别
- 新 mobi8/KF8 返回 epub 文件 -> 直接复用 EpubReader 的章节解析
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from ..models import Book
from .base import BaseReader
from .epub_reader import EpubReader

logger = logging.getLogger("book2audio.reader.mobi")


class MobiReader(BaseReader):
    def __init__(self, patterns: Optional[list[str]] = None):
        super().__init__(patterns)
        self._epub_helper = EpubReader(patterns or [])

    def _read_raw(self, path: Path) -> str:
        raise NotImplementedError("mobi 读取走 read()")

    def read(self, path: str | Path, book_title: Optional[str] = None) -> Book:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"图书文件不存在: {p}")
        try:
            import mobi  # 延迟导入
        except ImportError as e:
            raise RuntimeError(
                "缺少 mobi 解析依赖，请先安装：pip install mobi"
            ) from e

        # mobi.extract 内部会自建临时目录（prefix=mobiex）并在其中解包整本书，
        # 再以第一个返回值把该目录路径交回调用方；库本身不会清理它，必须由我们回收，
        # 否则每次转换泄漏一个目录（实测单本 800K+，大书可达数十 MB）。
        extracted_dir: Optional[str] = None
        try:
            extracted_dir, out_path = mobi.extract(str(p))
            out_file = Path(out_path)
            if not out_file.exists():
                # mobi 库可能返回相对路径
                out_file = Path(extracted_dir) / out_path
            suffix = out_file.suffix.lower()

            if suffix == ".epub":
                # mobi8/KF8 转出的 epub：复用 epub 解析
                book = self._epub_helper.read(out_file, book_title=book_title)
                # 修正 source 信息为原始 mobi
                book.source_path = str(p)
                book.source_format = "mobi"
                return book
            # mobi7/老格式：HTML -> 文本 -> 正则识别
            text = self._epub_helper._html_to_text(out_file.read_text(encoding="utf-8", errors="ignore"))
        except Exception as e:
            raise RuntimeError(f"mobi 解包失败: {e}") from e
        finally:
            # 递归删除前先确认目标仍在系统临时目录下，
            # 避免第三方库返回异常路径时误删用户文件。
            if extracted_dir:
                resolved = Path(extracted_dir).resolve()
                tmp_root = Path(tempfile.gettempdir()).resolve()
                if resolved != tmp_root and tmp_root in resolved.parents:
                    shutil.rmtree(resolved, ignore_errors=True)
                else:
                    logger.warning("跳过清理非临时目录（疑似异常路径）：%s", extracted_dir)

        chapters = self.detector.split(text)
        if not chapters:
            raise ValueError(f"无法从 mobi 中解析出章节: {p}")
        title = book_title or p.stem
        return Book(title=title, source_path=str(p), source_format="mobi", chapters=chapters)
