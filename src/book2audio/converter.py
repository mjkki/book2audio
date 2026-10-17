"""转换编排：一本书 -> 逐章 mp3 + lrc + json + manifest。"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import time
from pathlib import Path

from .models import Book, Chapter, ChapterResult, Segment
from .parser.segmenter import split_chapter
from .parser.text_cleaner import compact_whitespace
from .tts.edge_tts_client import EdgeTTSClient
from .tts.audio import concat_mp3
from .subtitle.lrc_writer import build_lrc
from .output.naming import chapter_basename, book_dir_name
from .output.manifest import write_manifest
from .config import Settings
from .utils.filesystem import ensure_dir

logger = logging.getLogger("book2audio.converter")


class Converter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.tts = EdgeTTSClient(
            voice=settings.get("voice"),
            rate=settings.get("rate"),
            volume=settings.get("volume"),
            pitch=settings.get("pitch"),
            max_attempts=settings.get_retry().get("max_attempts", 5),
            backoff_sec=settings.get_retry().get("backoff_sec", 2.0),
            connect_pace_sec=settings.get_retry().get("connect_pace_sec", 0.5),
            duration_estimate=settings.get_duration_estimate(),
        )
        self.overwrite: bool = settings.get("overwrite", False)
        self.resume: bool = settings.get("resume", False)
        self.audio_format: str = settings.get("audio_format", "mp3")
        self.bitrate: str = settings.get("bitrate", "64k")
        self.gap_sec: float = settings.get("segment_gap_sec", 0.25)
        self.padding: int = settings.get("padding", 2)
        seg_cfg = settings.get_segment()
        self.max_chars: int = seg_cfg.get("max_chars", 500)
        self.min_chars: int = seg_cfg.get("min_chars", 30)
        # 调试开关：True 时保留临时片段目录（默认 False，转换后自动回收）
        self.keep_segments: bool = settings.get("keep_segments", False)

    # ---------- 公共入口 ----------

    def convert(self, book: Book, out_root: Path) -> list[ChapterResult]:
        started = time.time()
        out_dir = ensure_dir(out_root / book_dir_name(book.title))
        results: list[ChapterResult] = []

        for chapter in book.chapters:
            logger.info("[%d/%d] 处理章节：%s", chapter.index, len(book.chapters), chapter.title)
            result = self._convert_chapter(chapter, out_dir, book_title=book.title)
            results.append(result)
            if result.status == "ok":
                logger.info("  完成 → %s (%.1f s)", Path(result.mp3_path).name, result.duration)
            elif result.status == "skipped":
                logger.info("  跳过（已存在）")
            else:
                logger.error("  失败：%s", result.error)

        manifest = write_manifest(book, results, self.settings.values, started, out_dir)
        logger.info("manifest 已写入: %s", manifest)
        return results

    # ---------- 单章 ----------

    def _convert_chapter(self, chapter: Chapter, out_dir: Path, book_title: str = "") -> ChapterResult:
        ext = self.audio_format
        stem = chapter_basename(chapter.index, chapter.title, ext, self.padding)
        mp3_path = out_dir / stem
        lrc_path = out_dir / stem.replace(f".{ext}", ".lrc")
        json_path = out_dir / stem.replace(f".{ext}", ".json")

        if not self.overwrite and self.resume and mp3_path.exists() and mp3_path.stat().st_size > 0:
            dur = _probe_len(mp3_path)
            if lrc_path.exists() and json_path.exists():
                return ChapterResult(chapter=chapter, status="skipped", mp3_path=str(mp3_path),
                                     lrc_path=str(lrc_path), json_path=str(json_path), duration=dur)

        seg_dir: Path | None = None
        try:
            segments = split_chapter(chapter.content, self.max_chars, self.min_chars)
            if not segments:
                raise ValueError("章节内容为空，无可合成文本")

            logger.debug("  切分为 %d 个片段", len(segments))
            segs, seg_dir = self._synthesize_chapter(segments, chapter)
            concat_mp3([s.audio_path for s in segs], mp3_path, gap_sec=self.gap_sec, bitrate=self.bitrate)
            duration = _probe_len(mp3_path)
            # ffprobe/mutagen 都失败时，用片段时长之和兜底
            if duration <= 0 and segs:
                duration = sum(s.duration for s in segs) + self.gap_sec * max(0, len(segs) - 1)

            lrc = build_lrc(segs, chapter_title=chapter.title, album=book_title or chapter.title)
            lrc_path.write_text(lrc, encoding="utf-8")
            json_path.write_text(_chapter_json(chapter, segs, duration), encoding="utf-8")

            return ChapterResult(chapter=chapter, status="ok", mp3_path=str(mp3_path),
                                 lrc_path=str(lrc_path), json_path=str(json_path), duration=duration)
        except Exception as e:  # noqa: BLE001 - 单章失败不中断全书
            logger.exception("章节处理失败")
            return ChapterResult(chapter=chapter, status="failed", error=str(e))
        finally:
            # 无论成功失败都回收本章临时片段，避免大批量转换时临时目录无限膨胀
            if seg_dir is not None and not self.keep_segments:
                self._cleanup_segments(seg_dir)

    # ---------- 片段合成 ----------

    def _synthesize_chapter(self, segments: list[Segment], chapter: Chapter) -> tuple[list[Segment], Path]:
        """逐段合成，累计时间轴。返回 (已完成片段, 临时片段目录)。

        临时片段写入系统临时目录（不在输出目录），由调用方在拼接完成后
        通过 _cleanup_segments 回收；调试时可用 config `keep_segments: true` 保留。
        """
        seg_dir = Path(tempfile.mkdtemp(prefix=f"b2a_ch{chapter.index:03d}_"))
        cursor = 0.0
        done: list[Segment] = []
        for i, seg in enumerate(segments):
            text = compact_whitespace(seg.text)
            tmp = seg_dir / f"seg_{chapter.index:03d}_{i:03d}.mp3"
            audio = self.tts.synthesize(text, tmp)
            seg.audio_path = audio.audio_path
            seg.duration = audio.duration
            seg.start_time = cursor
            cursor += audio.duration + self.gap_sec
            done.append(seg)
        return done, seg_dir

    @staticmethod
    def _cleanup_segments(seg_dir: Path) -> None:
        """删除本章临时片段目录。

        护栏：仅当目录位于系统临时目录下且带 b2a_ch 前缀时才删除，
        防止异常路径误删用户文件；清理失败只告警，不影响转换结果。
        """
        try:
            resolved = seg_dir.resolve()
            tmp_root = Path(tempfile.gettempdir()).resolve()
            if resolved != tmp_root and tmp_root in resolved.parents and resolved.name.startswith("b2a_ch"):
                shutil.rmtree(resolved, ignore_errors=True)
            else:
                logger.warning("跳过清理非临时目录（疑似异常路径）：%s", seg_dir)
        except Exception:  # noqa: BLE001 - 清理失败不影响转换结果
            logger.warning("临时片段目录清理失败（不影响结果）：%s", seg_dir)


def _chapter_json(chapter: Chapter, segments: list[Segment], duration: float) -> str:
    data = {
        "index": chapter.index,
        "title": chapter.title,
        "duration_sec": round(duration, 2),
        "char_count": chapter.char_count,
        "segments": [
            {
                "start": round(s.start_time, 3),
                "duration": round(s.duration, 3),
                "text": s.text,
            }
            for s in segments
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def _probe_len(path: Path) -> float:
    try:
        from .tts.audio import probe_duration

        d = probe_duration(path)
        if d > 0:
            return d
    except Exception:  # noqa: BLE001
        pass
    try:
        from mutagen.mp3 import MP3

        return float(MP3(str(path)).info.length)
    except Exception:  # noqa: BLE001
        return 0.0
