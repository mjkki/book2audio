"""命令行入口。"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .config import load_settings
from .converter import Converter
from .reader.base import reader_for_format
from .output.naming import book_dir_name
from .tts.duration_estimator import estimate_duration, format_duration
from .utils.logging import setup_logging

logger = logging.getLogger("book2audio")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="book2audio",
        description="将图书按章节转换为带 lrc 歌词的 mp3 音频（基于微软 edge-tts）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  book2audio 书.txt --out ./output --voice zh-CN-XiaoxiaoNeural\n"
            "  book2audio 书.epub --dry-run --config config.yaml\n"
            "  book2audio 书.txt --resume --rate +10%\n"
        ),
    )
    p.add_argument("input", help="图书文件路径（支持 txt / epub / mobi）")
    p.add_argument("--out", dest="out", help="输出根目录（默认 ./output）")
    p.add_argument("--voice", help="TTS 音色，如 zh-CN-XiaoxiaoNeural（edge-tts 音色）")
    p.add_argument("--rate", help="语速，如 +0%%，-10%%，+20%%")
    p.add_argument("--pitch", help="音调，如 +0Hz、+10Hz")
    p.add_argument("--volume", help="音量，如 +0%%，+20%%")
    p.add_argument("--format", help="音频格式（默认 mp3）")
    p.add_argument("--config", help="配置文件路径（yaml）")
    p.add_argument("--chapter-pattern", action="append", default=None,
                   help="追加章节标题正则（可多次），如 '^第.*章'")
    p.add_argument("--segment-max-chars", type=int, default=None, help="TTS 片段最大字符数")
    p.add_argument("--gap", type=float, dest="segment_gap_sec", default=None, help="片段间停顿秒数（默认 0.25）")
    resume_group = p.add_mutually_exclusive_group()
    resume_group.add_argument("--overwrite", action="store_true", help="覆盖已有输出文件")
    resume_group.add_argument("--resume", action="store_true", help="跳过已完成章节（断点续跑）")
    p.add_argument("--dry-run", action="store_true", help="只解析并列出章节，不合成音频")
    p.add_argument("--list-voices", action="store_true", help="列出 edge-tts 可用音色")
    p.add_argument("--log-level", default=None, help="日志级别 DEBUG/INFO/WARNING/ERROR")
    p.add_argument("--version", action="version", version=f"book2audio {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_voices:
        from .tts.edge_tts_client import list_voices

        voices = list_voices()
        if not voices:
            print("获取音色列表失败（网络不可用？）")
            return 1
        for v in voices:
            print(v)
        return 0

    cli_overrides = {
        "voice": args.voice,
        "rate": args.rate,
        "pitch": args.pitch,
        "volume": args.volume,
        "audio_format": args.format,
        "output_dir": args.out,
        "segment_gap_sec": args.segment_gap_sec,
        "log_level": args.log_level,
        "resume": True if args.resume else None,
        "overwrite": True if args.overwrite else None,
    }
    if args.segment_max_chars is not None:
        cli_overrides["segment"] = {"max_chars": args.segment_max_chars}

    try:
        settings = load_settings(args.config, cli_overrides)
    except Exception as e:  # noqa: BLE001
        print(f"配置加载失败: {e}", file=sys.stderr)
        return 2

    setup_logging(settings.get("log_level", "INFO"))

    # 追加章节识别规则
    patterns = list(settings.chapter_pattern)
    if args.chapter_pattern:
        patterns.extend(args.chapter_pattern)

    input_path = Path(args.input)
    fmt = input_path.suffix.lstrip(".").lower()
    try:
        reader = reader_for_format(fmt, patterns)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2

    try:
        book = reader.read(input_path)
    except Exception as e:  # noqa: BLE001
        print(f"读取图书失败: {e}", file=sys.stderr)
        return 2

    print(f"书名：{book.title}")
    print(f"格式：{book.source_format}，共识别 {len(book.chapters)} 个章节：")
    total_chars = sum(c.char_count for c in book.chapters)
    for ch in book.chapters:
        print(f"  [{ch.index:02d}] {ch.title}  （{ch.char_count} 字）")
    print(f"全书正文约 {total_chars} 字")

    # 基于文字长度预估全书音频时长，方便用户直观判断转换后是否生成完全
    est_total = sum(
        estimate_duration(ch.content, rate=settings.get("rate", "+0%"))
        for ch in book.chapters
    )
    print(f"全书预估音频时长约 {format_duration(est_total)}（基于文字长度估算，实际可能略有出入）")

    if args.dry_run:
        print("\n[dry-run] 仅解析完成，未合成音频。")
        return 0

    out_root = Path(settings.get("output_dir", "./output"))
    try:
        converter = Converter(settings)
        results = converter.convert(book, out_root)
    except KeyboardInterrupt:
        print("\n已中断。重新执行时加 --resume 可继续。", file=sys.stderr)
        return 130
    except Exception as e:  # noqa: BLE001
        logger.exception("转换过程出错")
        print(f"转换失败: {e}", file=sys.stderr)
        return 2

    out_dir = out_root / book_dir_name(book.title)
    ok = sum(1 for r in results if r.status == "ok")
    skipped = sum(1 for r in results if r.status == "skipped")
    failed = sum(1 for r in results if r.status == "failed")
    print(f"\n完成：成功 {ok}，跳过 {skipped}，失败 {failed}")
    print(f"输出目录：{out_dir}")

    # 实际时长 vs 预估时长对照：口径对齐为「非失败章节」，避免失败章节稀释导致误告警
    failed_idx = {r.chapter.index for r in results if r.status == "failed"}
    actual_total = sum(r.duration or 0.0 for r in results if r.status != "failed")
    est_done = sum(
        estimate_duration(ch.content, rate=settings.get("rate", "+0%"))
        for ch in book.chapters
        if ch.index not in failed_idx
    )
    if actual_total > 0 and est_done > 0:
        ratio = actual_total / est_done
        print(f"全书实际音频时长约 {format_duration(actual_total)}（预估约 {format_duration(est_done)}）")
        if ratio < 0.7:
            print(
                "⚠️ 实际时长明显低于预估，可能存在截断，建议检查失败片段或重跑。",
                file=sys.stderr,
            )
    for r in results:
        if r.status == "failed":
            print(f"  [失败] 第{r.chapter.index}章 {r.chapter.title}: {r.error}", file=sys.stderr)
    if failed:
        print("存在失败章节，修复后可用 --resume 重跑未完成章节。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
