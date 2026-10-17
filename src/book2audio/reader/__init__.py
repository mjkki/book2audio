"""reader 包：各格式图书读取器。"""

from .base import BaseReader
from .txt_reader import TxtReader
from .epub_reader import EpubReader
from .mobi_reader import MobiReader

__all__ = ["BaseReader", "TxtReader", "EpubReader", "MobiReader"]
