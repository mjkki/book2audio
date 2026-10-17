"""单元测试：章节识别、文本清洗、句子切分、lrc 生成、输出命名。"""

from __future__ import annotations

import glob
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from book2audio.output.naming import sanitize_filename, chapter_stem, chapter_basename, book_dir_name
from book2audio.parser.chapter_detector import ChapterDetector
from book2audio.parser.text_cleaner import clean_text, compact_whitespace
from book2audio.parser.segmenter import split_chapter
from book2audio.subtitle.lrc_writer import build_lrc, format_timestamp
from book2audio.models import Chapter, Segment
from book2audio.config import load_settings, DEFAULT_CONFIG


# ============ ChapterDetector ============

PATTERNS = DEFAULT_CONFIG["chapter_pattern"]


def _detect(detector: ChapterDetector, text: str) -> list[Chapter]:
    cleaned = clean_text(text)
    return detector.split(cleaned)


class TestChapterDetector:
    def test_chinese_titles(self):
        d = ChapterDetector(PATTERNS)
        chapters = _detect(d, "序章\n\n这是序章的内容，故事从这里正式开始讲述。\n\n第一章 启程\n\n这是第一篇正文内容，主人公准备好了一切出发。\n\n第二章 山谷\n\n更多正文内容，故事继续深入讲述。")
        assert len(chapters) == 3
        assert chapters[0].title == "序章"
        assert chapters[1].title == "第一章 启程"
        assert chapters[2].title == "第二章 山谷"

    def test_english_titles(self):
        d = ChapterDetector(PATTERNS)
        chapters = _detect(d, "Prologue\n\nThe story begins here, introducing the main character and setting. It's a quiet morning.\n\nChapter 1\n\nThe body of the first chapter with substantial content and descriptions.\n\nChapter 2\n\nMore content for the second chapter with detailed narrative.")
        assert len(chapters) == 3
        assert chapters[0].title == "Prologue"
        assert chapters[1].title == "Chapter 1"
        assert chapters[2].title == "Chapter 2"

    def test_drops_toc(self):
        d = ChapterDetector(PATTERNS)
        chapters = _detect(d, (
            "目录页面\n序章\n第一章 启程\n第二章 山谷\n第三章 归途\n\n"
            "序章\n\n这是序章的正文内容，讲的是故事开始的背景。"
        ))
        # TOC 被丢弃后最后一个章节是真实章节"序章"
        assert len(chapters) >= 1
        assert chapters[-1].title == "序章"

    def test_no_title(self):
        d = ChapterDetector(PATTERNS)
        chapters = _detect(d, "纯文本，没有章节标题。只有内容。")
        assert len(chapters) == 1
        assert chapters[0].title == "全书"

    def test_mixed_titles(self):
        d = ChapterDetector(PATTERNS)
        chapters = _detect(d, (
            "卷一 风起\n\n正文。\n\n"
            "Chapter 2 雨夜\n\n正文。\n\n"
            "第三回 刀光\n\n正文。\n\n"
            "楔子\n\n正文。"
        ))
        assert len(chapters) >= 1

    def test_chapter_underscore_separator(self):
        """Chapter_1（下划线分隔）应被识别为章节标题。"""
        d = ChapterDetector(PATTERNS)
        assert d.is_title_line("Chapter_1")
        assert d.is_title_line("Chapter_3")
        assert d.is_title_line("Chapter 2")

    def test_numbered_list_not_title(self):
        """正文编号列表（1. 现代集团...）不应被误判为章节标题。"""
        d = ChapterDetector(PATTERNS)
        assert not d.is_title_line("1. 现代集团对汽车产业的期望很高，这是非常重要的一个判断")
        # 短编号标题仍应识别（如 "1. 初入江湖"）
        assert d.is_title_line("1. 初入江湖")

    def test_sanitized_filenames(self):
        """章节标题被清洗后不应有非法文件名字符。"""
        d = ChapterDetector(PATTERNS)
        chapters = _detect(d, "第一章 测试/\\:*?\"<>|\n\n正文。")
        for ch in chapters:
            safe = sanitize_filename(ch.title)
            assert "/" not in safe
            assert "\\" not in safe
            assert ":" not in safe


# ============ TextCleaner ============

class TestTextCleaner:
    def test_removes_zero_width(self):
        result = clean_text("a\u200bb\u200cc\ufeffd")
        # 零宽字符被直接删除，不替换为空格
        assert result == "abcd"

    def test_removes_page_numbers(self):
        # 页码格式被删除
        result = clean_text("正文。\n第 2 页\n- 12 -\n(23)\n正文。")
        assert "第 2 页" not in result
        assert "- 12 -" not in result
        assert "(23)" not in result

    def test_keeps_body_numbers(self):
        # 独立数字行是正文内容（年份/序号），不能被当页码删除
        result = clean_text("1945\n战争结束那年。\n2024\n数据如下。\n1\n列表项。\n35\n继续。")
        assert "1945" in result
        assert "2024" in result
        assert "1" in result
        assert "35" in result

    def test_normalizes_punctuation(self):
        result = clean_text("（测试）「引用」：你好；这是")
        assert "(" in result
        assert ")" in result
        assert ":" in result
        assert ";" in result

    def test_compresses_blank_lines(self):
        result = clean_text("a\n\n\n\n\nb")
        lines = result.split("\n")
        blank_streaks = 0
        for i, ln in enumerate(lines):
            if not ln.strip() and i > 0 and not lines[i - 1].strip():
                blank_streaks += 1
        assert blank_streaks == 0

    def test_compact_whitespace(self):
        assert compact_whitespace("a   b\nc\td") == "a b c d"


# ============ Segmenter ============

class TestSegmenter:
    def test_simple_paragraphs(self):
        segments = split_chapter("句号。叹号！问号？分号；第二句。", max_chars=500, min_chars=30)
        assert len(segments) == 1

    def test_long_text_split(self):
        long = "句号。" * 100 + "结束。"
        segments = split_chapter(long, max_chars=200, min_chars=30)
        assert len(segments) >= 2

    def test_short_merge(self):
        segments = split_chapter("短。很短。非常短。", max_chars=500, min_chars=10)
        merged_text = " ".join(s.text for s in segments)
        assert "短" in merged_text

    def test_empty_content(self):
        segments = split_chapter("   \n\n  ", max_chars=500, min_chars=30)
        assert len(segments) == 0


# ============ LrcWriter ============

class TestLrcWriter:
    def test_basic_lrc(self):
        segs = [Segment(text="第一句"), Segment(text="第二句")]
        segs[0].start_time = 0.0
        segs[0].duration = 2.0
        segs[1].start_time = 2.5
        segs[1].duration = 1.5
        lrc = build_lrc(segs, chapter_title="第一章", album="测试书")
        assert "[ti:第一章]" in lrc
        assert "[al:测试书]" in lrc
        assert "[ar:book2audio]" in lrc
        assert "[00:00.00]" in lrc
        assert "[00:02.50]" in lrc
        assert "第一句" in lrc
        assert "第二句" in lrc

    def test_empty_segments(self):
        lrc = build_lrc([], chapter_title="空白")
        assert lrc

    def test_format_timestamp(self):
        assert format_timestamp(0) == "00:00.00"
        assert format_timestamp(65.0) == "01:05.00"
        assert format_timestamp(3661.25) == "61:01.25"


# ============ Naming ============

class TestNaming:
    def test_sanitize(self):
        assert "/" not in sanitize_filename("a/b")
        assert "\\" not in sanitize_filename("a\\b")

    def test_chapter_stem(self):
        stem = chapter_stem(1, "第一章 测试", padding=2)
        assert stem == "01-第一章 测试"

    def test_chapter_basename(self):
        name = chapter_basename(2, "第二章", "mp3", padding=2)
        assert name == "02-第二章.mp3"

    def test_book_dir_name(self):
        name = book_dir_name("测试/书:名")
        assert "/" not in name
        assert ":" not in name


# ============ Config ============

class TestConfig:
    def test_defaults(self):
        s = load_settings()
        assert s.get("voice") == "zh-CN-XiaoxiaoNeural"
        assert s.get("rate") == "+0%"
        assert s.get("segment")["max_chars"] == 500

    def test_cli_overrides(self):
        s = load_settings(None, {"voice": "zh-CN-YunxiNeural", "rate": "+10%"})
        assert s.get("voice") == "zh-CN-YunxiNeural"
        assert s.get("rate") == "+10%"

    def test_config_file(self, tmp_path: Path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("voice: zh-CN-XiaoyiNeural\nrate: -10%\n", encoding="utf-8")
        s = load_settings(str(cfg))
        assert s.get("voice") == "zh-CN-XiaoyiNeural"
        assert s.get("rate") == "-10%"

    def test_cli_overrides_config(self, tmp_path: Path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("voice: zh-CN-XiaoyiNeural\n", encoding="utf-8")
        s = load_settings(str(cfg), {"voice": "zh-CN-YunxiNeural"})
        assert s.get("voice") == "zh-CN-YunxiNeural"


# ============ MobiReader 临时目录回收 ============

class TestMobiTempCleanup:
    """回归：mobi.extract 自建的解包临时目录必须被回收。

    背景：mobi.extract 内部 `tempfile.mkdtemp(prefix="mobiex")` 自建目录并把路径
    作为第一个返回值交回调用方，库本身不清理。旧实现只清理了自己新建的空目录，
    导致每次转换泄漏一个含完整解包书籍的目录（实测单本 800K+，大书数十 MB）。
    """

    _FIXTURE = (
        Path(__file__).resolve().parent.parent
        / "examples" / "books"
        / "经营未来 (李明博) (z-library.sk, 1lib.sk, z-lib.sk).mobi"
    )

    @staticmethod
    def _extract_dirs() -> set[str]:
        root = os.path.realpath(tempfile.gettempdir())
        return set(glob.glob(os.path.join(root, "mobiex*")))

    def test_extract_tempdir_is_cleaned_up(self):
        pytest.importorskip("mobi", reason="未安装 mobi，跳过解包清理回归")
        if not self._FIXTURE.exists():
            pytest.skip(f"缺少 mobi 夹具: {self._FIXTURE}")

        from book2audio.reader.mobi_reader import MobiReader

        before = self._extract_dirs()
        book = MobiReader().read(self._FIXTURE)
        after = self._extract_dirs()

        # 清理不能顺手把内容也弄没了：解析结果本身必须正常
        assert book.chapters, "mobi 解析结果为空，清理可能早于内容读取"
        assert book.source_format == "mobi"
        # 不能新增 mobiex* 残留
        assert not (after - before), f"泄漏了解包临时目录: {sorted(after - before)}"

    def test_non_temp_path_is_not_deleted(self, monkeypatch):
        """安全护栏：若 extract 返回非临时目录（异常路径），绝不递归删除。"""
        pytest.importorskip("mobi", reason="未安装 mobi，跳过护栏回归")
        if not self._FIXTURE.exists():
            pytest.skip(f"缺少 mobi 夹具: {self._FIXTURE}")

        import mobi as mobi_mod
        from book2audio.reader import mobi_reader as mr

        tmp_root = Path(tempfile.gettempdir()).resolve()
        outside = Path("/tmp").resolve()
        # 该用例依赖「/tmp 不在系统 TMPDIR 之下」，否则无法构造非临时路径
        if outside == tmp_root or tmp_root in outside.parents:
            pytest.skip("当前环境 /tmp 即系统临时目录，无法构造非临时路径")

        root = Path(tempfile.mkdtemp(prefix="b2a_guard_", dir=str(outside)))
        try:
            sentinel = root / "pretend_extract"
            sentinel.mkdir()
            target = sentinel / "book.html"
            target.write_text("<p>不该被删掉的正文</p>", encoding="utf-8")

            monkeypatch.setattr(mobi_mod, "extract", lambda _p: (str(sentinel), str(target)))
            mr.MobiReader().read(self._FIXTURE)

            assert sentinel.exists(), "护栏失效：非临时目录被递归删除"
            assert target.exists(), "护栏失效：用户文件被删除"
        finally:
            shutil.rmtree(root, ignore_errors=True)