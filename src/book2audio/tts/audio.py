"""音频拼接：把章节的多个片段 mp3 拼接为单个 mp3。

- gap_sec > 0 时在段间插入静音（与 lrc 时间轴保持一致）
- 使用 ffmpeg（concat demuxer 或 filter）
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger("book2audio.audio")


def concat_mp3(segment_paths: list[Path], out_path: Path, gap_sec: float = 0.25, bitrate: str = "64k") -> None:
    """按顺序拼接多个 mp3 片段，段间插入 gap_sec 秒静音。"""
    if not segment_paths:
        raise ValueError("没有可拼接的音频片段")
    # 统一转成绝对路径，避免 concat demuxer 相对路径解析问题
    segment_paths = [p.resolve() for p in segment_paths]
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if len(segment_paths) == 1 and gap_sec <= 0:
        # 单片段直接复制
        import shutil

        shutil.copyfile(segment_paths[0], out_path)
        return

    ffmpeg = _find_ffmpeg()

    if gap_sec <= 0:
        # 无损 concat（concat demuxer 以 list 文件所在目录为基准，必须用绝对路径）
        list_file = out_path.with_suffix(".concat.txt")
        try:
            with open(list_file, "w", encoding="utf-8") as f:
                for sp in segment_paths:
                    f.write(f"file '{sp.as_posix()}'\n")
            _run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(out_path)])
        finally:
            list_file.unlink(missing_ok=True)
        return

    # 带静音插入：逐段 apad，再 concat 过滤器（全部使用绝对路径）
    cmd = [ffmpeg, "-y"]
    filters: list[str] = []
    for i, sp in enumerate(segment_paths):
        cmd += ["-i", str(sp)]
        filters.append(f"[{i}:a]apad=pad_dur={gap_sec:.2f}[a{i}]")
    concat_in = "".join(f"[a{i}]" for i in range(len(segment_paths)))
    filters.append(f"{concat_in}concat=n={len(segment_paths)}:v=0:a=1[out]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "[out]", "-b:a", bitrate, str(out_path)]
    _run(cmd)


def probe_duration(path: Path) -> float:
    """用 ffprobe 获取音频时长（秒）。"""
    ffprobe = _find_ffprobe()
    out = subprocess.run(
        [ffprobe, "-v", "quiet", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True,
        text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def _find_ffmpeg() -> str:
    path = shutil.which("ffmpeg") or shutil.which("/opt/homebrew/bin/ffmpeg") or shutil.which("/usr/local/bin/ffmpeg")
    if path:
        return path
    raise RuntimeError("未找到 ffmpeg，请安装（macOS: brew install ffmpeg）")


def _find_ffprobe() -> str:
    path = shutil.which("ffprobe") or shutil.which("/opt/homebrew/bin/ffprobe") or shutil.which("/usr/local/bin/ffprobe")
    if path:
        return path
    raise RuntimeError("未找到 ffprobe，请安装 ffmpeg")


def _run(cmd: list[str]) -> None:
    logger.debug("执行: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 执行失败: {proc.stderr[-2000:]}")
