"""文件系统工具。"""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def temp_dir(prefix: str = "book2audio_"):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield d
    finally:
        import shutil

        shutil.rmtree(d, ignore_errors=True)
