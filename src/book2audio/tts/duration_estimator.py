"""基于文字长度预估音频时长。

edge-tts 是实时流式合成，单段音频时长 ≈ 文本在目标音色下的朗读时长。
不同字符类型语速不同，这里分类型加权估算：

- 中日韩表意字 (CJK)：按字数 × 系数（中文约 0.235s/字，XiaoxiaoNeural 实测）
- 拉丁连续串（英文单词 / 数字）：按「词」数 × 系数（约 0.32s/词）
- 标点 / 符号：按个数 × 系数（约 0.10s/个，含朗读自然停顿）

``rate``（如 "+10%" / "-20%"）会整体缩放时长。
"""

from __future__ import annotations

import re

_LATIN_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def estimate_duration(
    text: str,
    *,
    per_cjk_char: float = 0.235,
    per_latin_word: float = 0.32,
    per_punct: float = 0.10,
    rate: str = "+0%",
) -> float:
    """根据文字长度预估朗读时长（秒）。

    系数均可通过参数覆盖，以便适配不同音色 / 语速。
    """
    if not text:
        return 0.0

    cjk = 0
    punct = 0
    latin_words = 0
    for token in _LATIN_TOKEN_RE.findall(text):
        latin_words += 1
    for ch in text:
        if "一" <= ch <= "鿿":  # CJK 统一表意文字区
            cjk += 1
        elif not ch.isalnum() and not ch.isspace():
            punct += 1

    seconds = cjk * per_cjk_char + latin_words * per_latin_word + punct * per_punct

    rate_pct = _parse_rate(rate)
    # 防御 rate=-100% 之类的极端配置导致除零；非法值不缩放
    if rate_pct and rate_pct > -100:
        seconds *= 100.0 / (100.0 + rate_pct)
    return seconds


def char_weight(text: str) -> tuple[int, int, int]:
    """返回 (cjk字数, 拉丁词数, 符号数)，供截断校验判断文本规模。"""
    cjk = 0
    punct = 0
    latin_words = len(_LATIN_TOKEN_RE.findall(text))
    for ch in text:
        if "一" <= ch <= "鿿":
            cjk += 1
        elif not ch.isalnum() and not ch.isspace():
            punct += 1
    return cjk, latin_words, punct


def _parse_rate(rate: str | None) -> float:
    """解析 edge-tts 的 rate 字符串，如 "+10%" / "-20%" -> 10.0 / -20.0；无法解析返回 0.0。"""
    if not rate:
        return 0.0
    m = re.search(r"([+-]?\d+(?:\.\d+)?)", rate)
    return float(m.group(1)) if m else 0.0


def format_duration(seconds: float) -> str:
    """把秒数格式化为中文「X 小时 Y 分 Z 秒」。"""
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} 小时 {m} 分 {s} 秒"
    if m:
        return f"{m} 分 {s} 秒"
    return f"{s} 秒"
