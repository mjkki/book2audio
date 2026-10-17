"""集成测试：端到端转换流程（mock TTS，不依赖网络）。

验证：
- 读取 -> 章节识别 -> 片段合成 -> 拼接 -> lrc/json/manifest 输出
- resume / overwrite 行为
- 单章失败不中断全书
- dry-run 只解析不合成
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from book2audio.config import load_settings
from book2audio.converter import Converter
from book2audio.models import Book, Chapter
from book2audio.output.naming import book_dir_name


def _make_book(tmp_path: Path) -> Book:
    """构造一本 3 章的小书。"""
    return Book(
        title="集成测试书",
        source_path="fake.txt",
        source_format="txt",
        chapters=[
            Chapter(index=1, title="第一章 开始", content="这是第一段正文，介绍故事的开始。" * 5),
            Chapter(index=2, title="第二章 发展", content="这是第二段正文，故事继续向前推进。" * 5),
            Chapter(index=3, title="第三章 结束", content="这是第三段正文，故事迎来了结局。" * 5),
        ],
    )


class FakeSegmentAudio:
    def __init__(self, audio_path, duration, words=None):
        self.audio_path = audio_path
        self.duration = duration
        self.words = words or []


class FakeTTS:
    """模拟 edge-tts：复制一个真实静音 mp3（ffmpeg 生成）作为片段，返回固定时长。"""

    _duration = 2.0
    _template: Path | None = None

    @classmethod
    def _ensure_template(cls, tmp_base: Path) -> Path:
        if cls._template and cls._template.exists():
            return cls._template
        import subprocess

        tpl = tmp_base / "silence.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "1", "-b:a", "48k", str(tpl)],
            capture_output=True,
        )
        cls._template = tpl
        return tpl

    def __init__(self, tmp_base: Path | None = None):
        self.tmp_base = tmp_base or Path("/tmp")

    def synthesize(self, text, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._ensure_template(self.tmp_base), out_path)
        return FakeSegmentAudio(audio_path=out_path, duration=self._duration)


class TestConverterIntegration:
    def test_full_conversion(self, tmp_path: Path):
        book = _make_book(tmp_path)
        settings = load_settings(None, {"output_dir": str(tmp_path / "out")})
        conv = Converter(settings)
        conv.tts = FakeTTS(tmp_path)  # type: ignore
        out_root = tmp_path / "out"

        results = conv.convert(book, out_root)
        assert len(results) == 3
        assert all(r.status == "ok" for r in results)

        out_dir = out_root / book_dir_name(book.title)
        # 三件套齐全且同章命名一致
        for i in (1, 2, 3):
            stem = f"0{i}-"
            mp3 = list(out_dir.glob(f"{stem}*.mp3"))
            lrc = list(out_dir.glob(f"{stem}*.lrc"))
            jsonf = list(out_dir.glob(f"{stem}*.json"))
            assert len(mp3) == 1 and len(lrc) == 1 and len(jsonf) == 1
            assert mp3[0].stat().st_size > 0
            # 同名主干
            assert mp3[0].stem == lrc[0].stem == jsonf[0].stem

        # manifest
        manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["summary"]["ok"] == 3
        assert manifest["book"]["title"] == "集成测试书"
        assert manifest["chapters"][0]["title"] == "第一章 开始"

        # lrc 内容
        lrc = (out_dir / "01-第一章 开始.lrc").read_text(encoding="utf-8")
        assert "[ti:第一章 开始]" in lrc
        assert "[00:00.00]" in lrc

    def test_resume_skips_existing(self, tmp_path: Path):
        book = _make_book(tmp_path)
        out_root = tmp_path / "out"
        out_dir = out_root / book_dir_name(book.title)
        out_dir.mkdir(parents=True, exist_ok=True)
        # 预置第一章文件
        (out_dir / "01-第一章 开始.mp3").write_bytes(b"ID3fake")
        (out_dir / "01-第一章 开始.lrc").write_text("[00:00.00]x", encoding="utf-8")
        (out_dir / "01-第一章 开始.json").write_text("{}", encoding="utf-8")

        settings = load_settings(None, {"output_dir": str(out_root), "resume": True})
        conv = Converter(settings)
        conv.tts = FakeTTS(tmp_path)  # type: ignore
        results = conv.convert(book, out_root)

        assert results[0].status == "skipped"
        assert results[1].status == "ok"
        assert results[2].status == "ok"

    def test_overwrite_regenerates(self, tmp_path: Path):
        book = _make_book(tmp_path)
        out_root = tmp_path / "out"
        out_dir = out_root / book_dir_name(book.title)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "01-第一章 开始.mp3").write_bytes(b"OLD")
        (out_dir / "01-第一章 开始.lrc").write_text("OLD", encoding="utf-8")
        (out_dir / "01-第一章 开始.json").write_text("{}", encoding="utf-8")

        settings = load_settings(None, {"output_dir": str(out_root), "overwrite": True})
        conv = Converter(settings)
        conv.tts = FakeTTS(tmp_path)  # type: ignore
        results = conv.convert(book, out_root)
        assert results[0].status == "ok"
        new_mp3 = (out_dir / "01-第一章 开始.mp3").read_bytes()
        assert new_mp3 != b"OLD"

    def test_single_chapter_failure_continues(self, tmp_path: Path, monkeypatch):
        book = _make_book(tmp_path)
        settings = load_settings(None, {"output_dir": str(tmp_path / "out")})
        conv = Converter(settings)
        conv.tts = FakeTTS(tmp_path)  # type: ignore

        def failing_synth(text, out_path):
            if "第二段正文" in text:
                raise RuntimeError("模拟 TTS 失败")
            return FakeTTS.synthesize(conv.tts, text, out_path)

        monkeypatch.setattr(conv.tts, "synthesize", failing_synth)
        results = conv.convert(book, tmp_path / "out")

        statuses = {r.chapter.index: r.status for r in results}
        assert statuses[1] == "ok"
        assert statuses[2] == "failed"
        assert statuses[3] == "ok"

    def test_dry_run_no_audio(self, tmp_path: Path, capsys):
        """dry-run 走 CLI 层：只列章节不合成。"""
        from book2audio.cli import main

        book_file = tmp_path / "dry.txt"
        book_file.write_text("第一章 测试\n\n这是正文内容。\n\n第二章 继续\n\n更多内容。", encoding="utf-8")
        rc = main([str(book_file), "--dry-run", "--out", str(tmp_path / "dryout")])
        out = capsys.readouterr().out
        assert rc == 0
        assert "[dry-run]" in out
        assert not (tmp_path / "dryout").exists()

    def test_invalid_format_returns_error(self, tmp_path: Path):
        from book2audio.cli import main

        bad = tmp_path / "book.pdf"
        bad.write_bytes(b"%PDF-1.4")
        rc = main([str(bad), "--dry-run"])
        assert rc == 2

    def test_missing_file_returns_error(self, tmp_path: Path, capsys):
        from book2audio.cli import main

        rc = main([str(tmp_path / "nonexistent.txt"), "--dry-run"])
        assert rc == 2