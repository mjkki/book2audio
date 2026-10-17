"""epub 读取器。

流程：
1. 解析 META-INF/container.xml 找到 OPF
2. 解析 OPF 的 metadata（书名）与 spine（阅读顺序）
3. 按 spine 顺序提取每个 HTML 的文本
4. 优先用 toc（NCX / nav）生成章节边界；失败则回退到统一正则识别
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from ..models import Book, Chapter
from .base import BaseReader

NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
OPF_NS = "http://www.idpf.org/2007/opf"


class EpubReader(BaseReader):
    def __init__(self, patterns: Optional[list[str]] = None):
        super().__init__(patterns)
        self._title = ""

    def _read_raw(self, path: Path) -> str:
        raise NotImplementedError("epub 读取走 read()，不走 _read_raw")

    def read(self, path: str | Path, book_title: Optional[str] = None) -> Book:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"图书文件不存在: {p}")
        with zipfile.ZipFile(p) as zf:
            entries = {name: self._decode(zf, name) for name in zf.namelist() if not name.endswith("/")}

        opf_path = self._find_opf(entries)
        opf_xml = entries[opf_path]
        root = ET.fromstring(opf_xml)
        self._title = book_title or self._extract_title(root) or p.stem

        spine_hrefs, item_map = self._extract_spine(root, opf_path)
        # spine 顺序的 HTML 块文本
        block_texts: list[str] = []
        for href in spine_hrefs:
            rel = self._resolve(href, opf_path)
            html = entries.get(rel) or entries.get(href)
            if html:
                block_texts.append(self._html_to_text(html))

        chapters = self._build_chapters(block_texts)
        if not chapters:
            raise ValueError(f"无法从 epub 中解析出章节: {p}")
        return Book(title=self._title, source_path=str(p), source_format="epub", chapters=chapters)

    # ---------- 内部工具 ----------

    @staticmethod
    def _decode(zf: zipfile.ZipFile, name: str) -> str:
        data = zf.read(name)
        for enc in ("utf-8-sig", "gb18030", "utf-16"):
            try:
                return data.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return data.decode("utf-8", errors="ignore")

    def _find_opf(self, entries: dict[str, str]) -> str:
        container = entries.get("META-INF/container.xml")
        if container:
            root = ET.fromstring(container)
            for elem in root.iter():
                if elem.tag.endswith("rootfile"):
                    path = elem.get("full-path")
                    if path and path in entries:
                        return path
        # 兜底：找第一个 .opf
        for name in entries:
            if name.lower().endswith(".opf"):
                return name
        raise ValueError("无法定位 epub 的 OPF 文件（container.xml 缺失）")

    def _extract_title(self, root: ET.Element) -> str:
        for meta in root.findall(f".//{{{OPF_NS}}}metadata/{{{OPF_NS}}}title"):
            if meta.text and meta.text.strip():
                return meta.text.strip()
        for meta in root.iter():
            if meta.tag.split("}")[-1] == "title" and meta.text:
                return meta.text.strip()
        return ""

    def _extract_spine(self, root: ET.Element, opf_path: str) -> tuple[list[str], dict[str, str]]:
        item_map: dict[str, str] = {}
        manifest = root.find(f".//{{{OPF_NS}}}manifest")
        if manifest is not None:
            for item in manifest.findall(f"{{{OPF_NS}}}item"):
                item_id = item.get("id")
                href = item.get("href", "")
                media = item.get("media-type", "")
                if media.startswith("text/") or href.lower().endswith((".html", ".htm", ".xhtml")):
                    item_map[item_id] = href

        spine = root.find(f".//{{{OPF_NS}}}spine")
        hrefs: list[str] = []
        if spine is not None:
            for itemref in spine.findall(f"{{{OPF_NS}}}itemref"):
                idref = itemref.get("idref")
                if idref in item_map:
                    hrefs.append(item_map[idref])
        return hrefs, item_map

    @staticmethod
    def _resolve(href: str, opf_path: str) -> str:
        base = opf_path.rsplit("/", 1)[0]
        if base:
            return f"{base}/{href}"
        return href

    @staticmethod
    def _html_to_text(html: str) -> str:
        # 处理双重转义：部分出版方会把 <b> 写成 &lt;b&gt;（再被转义一次）
        # 需要解码两次，让标签恢复真实结构，否则 <b> 会以文本形式残留并被误判为标题
        html = html.replace("&amp;lt;", "&lt;").replace("&amp;gt;", "&gt;")
        html = html.replace("&lt;", "<").replace("&gt;", ">")
        html = html.replace("&amp;nbsp;", "&nbsp;").replace("&amp;amp;", "&amp;")

        soup = BeautifulSoup(html, "lxml")
        # 删除脚本/样式/注释及不可见内容
        for tag in soup(["script", "style", "svg", "title", "meta", "link", "head"]):
            tag.decompose()
        # 标题标签保留换行，方便识别
        for tag in soup.find_all(re.compile(r"^h[1-6]$")):
            tag.insert_after("\n")
            tag.append("\n")
        for tag in soup.find_all(["p", "div", "br", "li"]):
            tag.append("\n")
        # 行内标签只取内容，去掉标签本身
        for tag in soup.find_all(re.compile(r"^(b|strong|i|em|span|u|font|a|small|big)$")):
            tag.unwrap()
        text = soup.get_text("\n")
        # 兜底清理：注释残留、残留标签、多余空行
        text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _build_chapters(self, block_texts: list[str]) -> list[Chapter]:
        """优先按 HTML 块内标题标签切分；否则统一走正则。"""
        chapters: list[Chapter] = []
        for block in block_texts:
            block_chapters = self._split_block(block)
            chapters.extend(block_chapters)
        if not chapters:
            chapters = self.detector.split("\n\n".join(block_texts))
        chapters = self._drop_toc_like_chapters(chapters)
        chapters = self._drop_duplicate_tail(chapters)
        # 重新编号
        for i, ch in enumerate(chapters, start=1):
            ch.index = i
        return chapters

    @staticmethod
    def _drop_duplicate_tail(chapters: list[Chapter]) -> list[Chapter]:
        """丢弃末尾的目录残留：标题与前面章节重复、且内容极短（<10 字）。

        典型形态：书末的索引/目录页被切成了独立章节，内容只有"目录"两字
        或几乎为空，标题却与前面的正文章节完全相同。
        """
        if len(chapters) < 2:
            return chapters
        seen_titles: set[str] = set()
        keep: list[Chapter] = []
        for ch in chapters:
            content_len = len(ch.content.strip())
            # 内容极短且标题已出现过 -> 目录残留
            if content_len < 10 and ch.title in seen_titles:
                continue
            seen_titles.add(ch.title)
            keep.append(ch)
        return keep

    @staticmethod
    def _drop_toc_like_chapters(chapters: list[Chapter]) -> list[Chapter]:
        """删除"目录页/版权页"章节：位于开头、内容几乎完全由标题列表组成。

        典型形态：
        - 目录页被切成独立章节（内容就是各章节标题列表，与正文标题重复）
        - 版权页/CIP 数据（含 ISBN、版编目、版权页等特征）
        目录页总是出现在书的最前面；版权页可能在开头或末尾。
        """
        if len(chapters) < 3:
            return chapters
        titles = [c.title for c in chapters if c.title]

        def _is_toc_like(ch: Chapter) -> bool:
            lines = [l.strip() for l in ch.content.split("\n") if l.strip()]
            if not lines:
                return True
            if len(lines) > 30:
                return False
            # 版权页/CIP 特征：含 ISBN/版编目/版权页 等
            joined = ch.title + "\n" + ch.content
            if re.search(r"(ISBN\s*\d|版权页|在版编目|版编目|版权所有|All rights reserved)", joined, re.IGNORECASE):
                return True
            # 内容行与任一章节标题完全一致的比例（目录项可能比正文标题多/少几个，阈值放宽到 0.5）
            matched = sum(1 for l in lines if any(l == t for t in titles))
            return matched / len(lines) >= 0.5

        # 从开头连续丢弃目录页/版权页
        i = 0
        while i < len(chapters) and _is_toc_like(chapters[i]):
            i += 1
        if i > 0:
            chapters = chapters[i:]

        # 从末尾丢弃版权页（CIP 数据通常在书末）
        j = len(chapters)
        while j > 0 and _is_toc_like(chapters[j - 1]):
            j -= 1
        if j < len(chapters):
            chapters = chapters[:j]
        return chapters

    def _split_block(self, block: str) -> list[Chapter]:
        """一个 spine 块：若内部含多个标题行则细切，否则整体一章。"""
        # 跳过封面/目录导航等无正文块（内容过短且无句末标点）
        if self._is_cover_or_toc(block):
            return []
        lines = block.split("\n")
        title_positions = [i for i, ln in enumerate(lines) if self.detector.is_title_line(ln) or self._is_heading(lines, i)]
        result: list[Chapter] = []
        if not title_positions:
            first = self._find_first_heading_line(lines)
            body = "\n".join(l for l in lines if l.strip()).strip()
            if body:
                result.append(Chapter(index=0, title=first or "", content=body))
            return result
        for pos, idx in enumerate(title_positions):
            end = title_positions[pos + 1] if pos + 1 < len(title_positions) else len(lines)
            title = lines[idx].strip()
            body = "\n".join(l for l in lines[idx + 1 : end] if l.strip()).strip()
            if body:
                result.append(Chapter(index=0, title=title, content=body))
        return result

    @staticmethod
    def _is_cover_or_toc(block: str) -> bool:
        """判断是否为封面页/目录导航页。

        两类判定：
        1. 内容很短（<40 字）且无句末标点 -> 封面/目录
        2. 含典型目录导航特征（Content / Chapter_X / 目录 且无正文句号）-> 目录页
        避免误杀短章节（如诗歌、对话、过渡段等合法正文）。
        """
        stripped = "\n".join(l for l in block.split("\n") if l.strip()).strip()
        if not stripped:
            return True
        has_sentence_end = bool(re.search(r"[。！？；…!?;]", stripped))
        if len(stripped) < 40 and not has_sentence_end:
            return True
        # 目录导航页：很短且含 Content/Chapter_X/目录 等导航特征
        if len(stripped) < 200 and not has_sentence_end and re.search(
            r"\b(Content|Chapter_\d+|目录|CONTENTS)\b", stripped, re.IGNORECASE
        ):
            return True
        return False

    @staticmethod
    def _is_heading(lines: list[str], i: int) -> bool:
        return bool(re.match(r"^[第序楔引附]{1,2}[\d一二三四五六七八九十百千]*[章节回卷部篇].{0,20}$", lines[i].strip()))

    def _find_first_heading_line(self, lines: list[str]) -> str:
        for ln in lines:
            s = ln.strip()
            # 含残留标签/实体（<、>、&）的行不是标题，避免误吞正文
            if re.search(r"[<>&]", s):
                continue
            if s and len(s) <= 30 and not re.search(r"[。！？.!?]", s):
                return s
        return ""
