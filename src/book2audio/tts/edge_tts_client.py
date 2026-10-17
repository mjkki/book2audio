"""edge-tts 合成客户端。

- 逐段合成 mp3，采集 WordBoundary 事件获取精确时间轴
- 支持重试与退避
- 段时长优先用 WordBoundary 计算，缺失时回退到 mutagen 读取
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import edge_tts
from mutagen.mp3 import MP3

from .duration_estimator import char_weight, estimate_duration

logger = logging.getLogger("book2audio.tts")

# 截断校验的默认系数（可被 config.duration_estimate 覆盖）
_DEFAULT_DURATION_ESTIMATE: dict = {
    "per_cjk_char": 0.235,
    "per_latin_word": 0.32,
    "per_punct": 0.10,
    "truncation_tolerance": 0.6,
}


@dataclass
class SegmentAudio:
    """一段合成结果。"""

    audio_path: Path
    duration: float  # 秒
    words: Optional[list[tuple[str, float, float]]] = None  # (text, offset_sec, duration_sec)


class EdgeTTSClient:
    def __init__(
        self,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
        max_attempts: int = 5,
        backoff_sec: float = 2.0,
        connect_timeout: int = 10,
        receive_timeout: int = 60,
        connect_pace_sec: float = 0.5,
        duration_estimate: Optional[dict] = None,
    ):
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.pitch = pitch
        self.max_attempts = max(1, max_attempts)
        self.backoff_sec = backoff_sec
        self.connect_timeout = connect_timeout
        self.receive_timeout = receive_timeout
        # 连接节流：每段合成前短暂休眠，降低单位时间新建连接数，
        # 规避 edge-tts 按 IP 的连接限流 / 偶发 IPv6 握手超时。
        self.connect_pace_sec = max(0.0, connect_pace_sec)
        # 时长预估 / 截断校验配置：实际时长低于「预估 × 容差」即判截断重试。
        self.duration_estimate = {**_DEFAULT_DURATION_ESTIMATE, **(duration_estimate or {})}

    def synthesize(self, text: str, out_path: Path) -> SegmentAudio:
        """同步包装的逐段合成（内部跑事件循环）。"""
        return asyncio.run(self._synthesize_async(text, out_path))

    async def _synthesize_async(self, text: str, out_path: Path) -> SegmentAudio:
        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                # 连接节流：仅首次尝试前休眠，避免连续新建连接触发限流
                if self.connect_pace_sec > 0 and attempt == 1:
                    await asyncio.sleep(self.connect_pace_sec)
                return await self._once(text, out_path)
            except Exception as e:  # noqa: BLE001 - 网络/TTS 错误统一重试
                last_err = e
                logger.warning("片段合成失败(第 %d/%d 次): %s", attempt, self.max_attempts, e)
                if attempt < self.max_attempts:
                    # 指数退避 + 抖动，给边缘节点/限流足够恢复时间
                    delay = min(self.backoff_sec * (2 ** (attempt - 1)), 30.0)
                    jitter = random.uniform(0, delay * 0.3)
                    await asyncio.sleep(delay + jitter)
        raise RuntimeError(f"片段合成多次失败: {last_err}") from last_err

    async def _once(self, text: str, out_path: Path) -> SegmentAudio:
        comm = edge_tts.Communicate(
            text,
            voice=self.voice,
            rate=self.rate,
            volume=self.volume,
            pitch=self.pitch,
            boundary="WordBoundary",
            connect_timeout=self.connect_timeout,
            receive_timeout=self.receive_timeout,
        )
        words: list[tuple[str, float, float]] = []
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            # 用 wait_for 硬超时兜底：aiohttp 在 SSL/连接层卡住时 receive_timeout 可能不触发
            async def _collect():
                async for chunk in comm.stream():
                    ctype = chunk["type"]
                    if ctype == "audio":
                        f.write(chunk["data"])
                    elif ctype == "WordBoundary":
                        offset_sec = chunk["offset"] / 1e7
                        dur_sec = chunk["duration"] / 1e7
                        words.append((chunk.get("text", ""), offset_sec, dur_sec))

            await asyncio.wait_for(_collect(), timeout=self.receive_timeout * 4)

        size = out_path.stat().st_size
        if size == 0:
            raise RuntimeError("edge-tts 返回空音频")
        # 以真实音频文件时长（mutagen）作为截断判定真值：WordBoundary 偶尔丢尾词
        # 会让 words 偏短，但音频本身可能是完整的，不能据此判失败。
        duration = self._duration_from_file(out_path) or self._duration_from_words(words)
        self._assert_not_truncated(text, duration)
        return SegmentAudio(audio_path=out_path, duration=duration, words=words)

    def _assert_not_truncated(self, text: str, duration: float) -> None:
        """基于文字长度预估时长，判断音频是否生成完全，不完整则抛错触发重试。

        判定真值取真实 mp3 文件时长（已在 _once 中以 mutagen 读取）。
        用 ``estimate_duration`` 按 CJK 字数 / 拉丁词数 / 符号数加权得到「预估时长」，
        实际时长低于「预估 × truncation_tolerance」即判为截断（edge-tts 偶发只返回部分音频）。
        文本规模过小时阈值不可靠，直接跳过校验。
        """
        cjk, latin_words, _punct = char_weight(text)
        if cjk + latin_words < 15:
            return
        est = estimate_duration(
            text,
            per_cjk_char=self.duration_estimate["per_cjk_char"],
            per_latin_word=self.duration_estimate["per_latin_word"],
            per_punct=self.duration_estimate["per_punct"],
            rate=self.rate,
        )
        lower = est * self.duration_estimate["truncation_tolerance"]
        if duration > 0 and duration < lower:
            raise RuntimeError(
                f"edge-tts 可能发生截断：实际 {duration:.1f}s 明显低于基于文字长度预估的 "
                f"{est:.1f}s（低于 {self.duration_estimate['truncation_tolerance']:.0%} 容差），已触发重试"
            )

    @staticmethod
    def _duration_from_words(words: list[tuple[str, float, float]]) -> float:
        if not words:
            return 0.0
        return max(o + d for _, o, d in words)

    @staticmethod
    def _duration_from_file(path: Path) -> float:
        try:
            return float(MP3(str(path)).info.length)
        except Exception:  # noqa: BLE001
            return 0.0


def list_voices() -> list[str]:
    """列出可用音色（网络请求）。"""
    try:
        return sorted(v["ShortName"] for v in asyncio.run(edge_tts.list_voices()))
    except Exception as e:  # noqa: BLE001
        logger.warning("获取音色列表失败: %s", e)
        return []
