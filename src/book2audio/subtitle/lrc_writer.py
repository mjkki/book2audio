"""lrc 歌词生成。"""

from __future__ import annotations

from typing import Iterable

from ..models import Segment


def format_timestamp(seconds: float) -> str:
    """把秒转成 lrc 时间标签 mm:ss.xx。"""
    if seconds < 0:
        seconds = 0.0
    minutes = int(seconds // 60)
    secs = seconds - minutes * 60
    return f"{minutes:02d}:{secs:05.2f}"


def build_lrc(
    segments: Iterable[Segment],
    chapter_title: str = "",
    album: str = "",
    artist: str = "book2audio",
    first_line_title: bool = True,
) -> str:
    """根据片段（含 start_time / text）生成 lrc 内容。"""
    lines: list[str] = []
    if chapter_title:
        lines.append(f"[ti:{chapter_title}]")
    if artist:
        lines.append(f"[ar:{artist}]")
    if album:
        lines.append(f"[al:{album}]")
    lines.append("[by:book2audio]")
    lines.append("")
    if first_line_title and chapter_title:
        lines.append(f"[{format_timestamp(0.0)}]{chapter_title}")
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        lines.append(f"[{format_timestamp(seg.start_time)}]{text}")
    return "\n".join(lines) + "\n"
