"""文本清洗：去除噪音，统一格式，为 TTS 合成做预处理。"""

from __future__ import annotations

import re

# 零宽字符
_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff\u2060]")
# 纯页码行：如 “第 1 页”、“- 12 -”、“(23)”（页眉页脚常见格式）
# 注意：独立纯数字行（如年份 1945、序号 1）是正文内容，不能删除！
_PAGE_LINE = re.compile(
    r"^[-\s]*(第\s*\d{1,4}\s*页|page\s*\d{1,4}|p\.\s*\d{1,4}|\(\s*\d{1,4}\s*\)|[\-—·\*]?\s*\d{1,4}\s*[\-—·\*])[-\s]*$",
    re.IGNORECASE,
)
# 连续 3 个以上相同分隔符的行（如 “***”、“————”）
_DECOR_LINE = re.compile(r"^([*—\-=_~·.。]{3,})$")
# 版权/网址/邮箱等噪音行（仅匹配明确的版权页特征，避免误删正文中 @提及、http 开头的正常句子）
_NOISE_LINE = re.compile(
    r"^(版权所有\s*[:：]?\s*\S+|Copyright\s*\(?c\)?\s*\d{4}|www\.\S+|https?://\S+|ISBN\s*\d+|^邮箱\s*[:：]\s*\S+)",
    re.IGNORECASE,
)


def clean_text(raw: str, remove_page_numbers: bool = True) -> str:
    """清洗整本图书文本。"""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = _ZERO_WIDTH.sub("", text)
    lines = []
    for ln in text.split("\n"):
        ln = ln.replace("\u3000", " ").strip()
        if not ln:
            lines.append("")
            continue
        if remove_page_numbers and _PAGE_LINE.match(ln):
            continue
        if _DECOR_LINE.match(ln):
            continue
        if _NOISE_LINE.match(ln):
            continue
        # 统一全角标点到半角（保留中文句号等常用中文标点）
        ln = _normalize_punct(ln)
        lines.append(ln)

    # 压缩连续空行
    out: list[str] = []
    prev_blank = False
    for ln in lines:
        if not ln:
            if not prev_blank:
                out.append("")
            prev_blank = True
        else:
            out.append(ln)
            prev_blank = False
    return "\n".join(out).strip()


def _normalize_punct(text: str) -> str:
    """常见全角转半角（括号、引号、逗号、空格等），中文句号保留。"""
    table = {
        "，": ",",
        "．": ".",
        "：": ":",
        "；": ";",
        "（": "(",
        "）": ")",
        "！": "!",
        "？": "?",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
    return "".join(table.get(ch, ch) for ch in text)


def compact_whitespace(text: str) -> str:
    """把空白（含换行）压成单个空格，用于片段内拼接。"""
    return re.sub(r"\s+", " ", text).strip()
