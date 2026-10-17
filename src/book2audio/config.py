"""配置加载与默认值。

优先级：命令行参数 > 配置文件 > 默认值。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "output_dir": "./output",
    "voice": "zh-CN-XiaoxiaoNeural",
    "rate": "+0%",
    "volume": "+0%",
    "pitch": "+0Hz",
    "audio_format": "mp3",
    "bitrate": "64k",
    "padding": 2,  # 章节序号补零位数
    "segment_gap_sec": 0.25,  # 段间停顿（秒），保持听感自然
    "chapter_pattern": [
        r"^第[0-9零一二三四五六七八九十百千万两]+[章节回卷部集篇]",
        r"^[卷部][一二三四五六七八九十零百千]+",
        r"^\d+\.\s+\S+",
        r"^Chapter[\s_.:-]+[0-9IVXLC]+\b",
        r"^CHAPTER[\s_.:-]+[0-9IVXLC]+\b",
        r"^(序章|楔子|引子|前言|序言|后记|尾声|番外|附录)",
        r"^(Prologue|Epilogue|Introduction|Foreword|Afterword|Appendix)\b",
    ],
    "segment": {
        "max_chars": 500,
        "min_chars": 30,
    },
    "retry": {
        "max_attempts": 5,
        "backoff_sec": 2.0,
        "connect_pace_sec": 0.5,
    },
    # 时长预估 / 截断校验：基于文字长度估算音频时长，实际时长低于「预估 × 容差」判截断
    "duration_estimate": {
        "per_cjk_char": 0.235,  # 每个中日韩表意字约 0.235 秒（XiaoxiaoNeural 实测）
        "per_latin_word": 0.32,  # 每个英文单词 / 数字串约 0.32 秒
        "per_punct": 0.10,  # 每个标点 / 符号约 0.10 秒（含自然停顿）
        "truncation_tolerance": 0.6,  # 实际时长需达到预估的 60% 才视为完整
    },
    "resume": False,
    "overwrite": False,
    "keep_segments": False,  # 调试开关：保留临时片段目录（默认转换后自动回收）
    "log_level": "INFO",
}

@dataclass
class Settings:
    """最终合并后的运行配置。"""

    values: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULT_CONFIG))
    config_path: Optional[str] = None

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def get_segment(self) -> dict[str, int]:
        return self.values.get("segment", DEFAULT_CONFIG["segment"])

    def get_retry(self) -> dict[str, float]:
        return self.values.get("retry", DEFAULT_CONFIG["retry"])

    def get_duration_estimate(self) -> dict[str, float]:
        # or 兜底：用户 yaml 写空值(duration_estimate:)时不返回 None
        return self.values.get("duration_estimate") or DEFAULT_CONFIG["duration_estimate"]

    @property
    def chapter_pattern(self) -> list[str]:
        return self.values.get("chapter_pattern", DEFAULT_CONFIG["chapter_pattern"])


def load_settings(config_path: Optional[str] = None, cli_overrides: Optional[dict] = None) -> Settings:
    """加载配置：默认值 -> 配置文件 -> 命令行覆盖。"""
    values = copy.deepcopy(DEFAULT_CONFIG)
    if config_path:
        p = Path(config_path)
        if not p.exists():
            raise FileNotFoundError(f"配置文件不存在: {p}")
        with open(p, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        _deep_merge(values, loaded)
    if cli_overrides:
        for key, val in cli_overrides.items():
            if val is not None:
                values[key] = val
    return Settings(values=values, config_path=config_path)


def _deep_merge(base: dict, extra: dict) -> None:
    """将 extra 深度合并进 base（extra 优先）。"""
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
