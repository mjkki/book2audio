"""日志配置。"""

from __future__ import annotations

import logging


def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
    level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    # 避免重复添加 handler
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
        root.addHandler(console)
    if log_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root.addHandler(fh)
