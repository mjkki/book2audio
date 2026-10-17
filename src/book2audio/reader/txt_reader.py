"""txt 读取器：自动检测编码，返回纯文本。"""

from __future__ import annotations

from pathlib import Path

from .base import BaseReader

_ENCODINGS = ("utf-8", "gb18030", "big5", "utf-16", "latin-1")


class TxtReader(BaseReader):
    def _read_raw(self, path: Path) -> str:
        data = path.read_bytes()
        # 优先尝试 utf-8-sig（带 BOM）
        for enc in ("utf-8-sig", *[e for e in _ENCODINGS if e != "utf-8"]):
            try:
                return data.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        # 兜底：忽略错误
        return data.decode("utf-8", errors="ignore")
