"""duration_estimator 与截断校验的单元测试。"""

from __future__ import annotations

import pytest

from book2audio.tts.duration_estimator import (
    char_weight,
    estimate_duration,
    format_duration,
)
from book2audio.tts.edge_tts_client import EdgeTTSClient


def test_estimate_duration_cjk_baseline():
    # 387 个中文字 ≈ 387 * 0.235 = 90.945s，与 XiaoxiaoNeural 实测(91.1s)高度吻合
    text = "时" * 387
    est = estimate_duration(text)
    assert 88.0 < est < 93.0


def test_estimate_duration_rate_speedup():
    text = "时" * 100
    base = estimate_duration(text, rate="+0%")
    faster = estimate_duration(text, rate="+10%")
    assert faster < base
    # +10% 语速 => 时长 ≈ 原时长的 100/110
    assert abs(faster - base * 100.0 / 110.0) < 0.5


def test_estimate_duration_latin_and_punct():
    text = "Hello world, 你好！"
    cjk, words, punct = char_weight(text)
    assert cjk == 2
    assert words == 2  # Hello, world
    assert punct >= 2  # 逗号、感叹号
    est = estimate_duration(text)
    assert est > 0


def test_format_duration():
    assert format_duration(45) == "45 秒"
    assert format_duration(90) == "1 分 30 秒"
    assert format_duration(3725) == "1 小时 2 分 5 秒"


def test_assert_not_truncated_passes_full_audio():
    cli = EdgeTTSClient()
    # 387 字正常约 91s，应判定完整（>= 预估*0.6）
    cli._assert_not_truncated("时" * 387, 91.0)


def test_estimate_duration_invalid_rate_no_crash():
    # 非法 / 极端 rate 不应崩溃（防御 -100% 除零、None、无数字）
    assert estimate_duration("时" * 10, rate="abc") > 0
    assert estimate_duration("时" * 10, rate="-100%") > 0  # 不缩放也不除零
    assert estimate_duration("时" * 10, rate=None) > 0


def test_assert_not_truncated_detects_clipping():
    cli = EdgeTTSClient()
    # 127 中文字预估约 29.8s，实际仅 17.3s（< 60% 容差）应判截断
    with pytest.raises(RuntimeError):
        cli._assert_not_truncated("时" * 127, 17.3)


def test_assert_not_truncated_skips_short_text():
    cli = EdgeTTSClient()
    # 文本规模太小(<15 个字符当量)不校验，不报错
    cli._assert_not_truncated("你好", 0.3)


def test_config_injected_into_client():
    cli = EdgeTTSClient(duration_estimate={"per_cjk_char": 0.235, "truncation_tolerance": 0.6})
    assert cli.duration_estimate["truncation_tolerance"] == 0.6
    # 未知键回退到默认
    assert cli.duration_estimate["per_latin_word"] == 0.32
