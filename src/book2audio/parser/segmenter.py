"""文本切分：把章节正文切成适合 TTS 合成的片段。

策略：
1. 先按段落（空行分隔）处理
2. 段内以句子标点（。！？；…）为优先切分点
3. 超过 max_chars 的长片段再按逗号/顿号二次切分
4. 合并过短片段，避免 lrc 过于碎片化
"""

from __future__ import annotations

import re

from ..models import Segment

# 句子级切分点
_SENT_END = re.compile(r"(?<=[。！？；…?!;])")
# 词级切分点（长句兜底）
_WORD_BREAK = re.compile(r"(?<=[,，、：:])")


def split_chapter(content: str, max_chars: int = 500, min_chars: int = 30) -> list[Segment]:
    """将章节正文切分为 TTS 片段。

    段划分以「空行」为准；段内的硬换行（许多 epub 每行一句）合并为空格，
    避免把每句话都切成独立片段——否则单章会产生上百个微型片段，
    导致 TTS 连接数爆炸、触发 edge-tts 的按 IP 连接限流。
    """
    # 按空行分段（兼容 \r\n）
    raw_paras = [p.strip() for p in re.split(r"\r?\n\s*\r?\n", content) if p.strip()]
    paragraphs: list[str] = []
    for p in raw_paras:
        # 段内换行（句子级）合并为空格
        joined = re.sub(r"\s*\r?\n\s*", " ", p).strip()
        if joined:
            paragraphs.append(joined)

    pieces: list[str] = []
    for para in paragraphs:
        pieces.extend(_split_paragraph(para, max_chars))

    # 合并过短片段
    merged = _merge_short(pieces, min_chars)
    return [Segment(text=p) for p in merged]


def _split_paragraph(para: str, max_chars: int) -> list[str]:
    if len(para) <= max_chars:
        return [para]

    # 按句子切
    sentences = [s.strip() for s in _SENT_END.split(para) if s.strip()]
    chunks: list[str] = []
    buf = ""
    for s in sentences:
        if len(s) > max_chars:
            # 超长句子：按词级切分点再拆
            parts = _split_long_sentence(s, max_chars)
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.extend(parts)
            continue
        if len(buf) + len(s) + 1 > max_chars and buf:
            chunks.append(buf)
            buf = s
        else:
            buf = (buf + " " + s).strip() if buf else s
    if buf:
        chunks.append(buf)
    return chunks


def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    parts = [p.strip() for p in _WORD_BREAK.split(sentence) if p.strip()]
    if len(parts) <= 1:
        # 没有任何可切点，只能硬切
        return [sentence[i : i + max_chars] for i in range(0, len(sentence), max_chars)]
    chunks: list[str] = []
    buf = ""
    for p in parts:
        if len(buf) + len(p) + 1 > max_chars and buf:
            chunks.append(buf)
            buf = p
        else:
            buf = (buf + " " + p).strip() if buf else p
    if buf:
        chunks.append(buf)
    return chunks


def _merge_short(pieces: list[str], min_chars: int) -> list[str]:
    merged: list[str] = []
    for p in pieces:
        if merged and len(merged[-1]) < min_chars:
            merged[-1] = merged[-1] + " " + p
        else:
            merged.append(p)
    return merged
