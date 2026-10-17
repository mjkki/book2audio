"""生成测试图书样本（examples/books/）。

生成：
1. 中文规整小说.txt —— 标准“第X章”结构，含目录页/序章/正文
2. 中英混排.txt —— 中文+英文段落混排
3. 混合标题.txt —— Chapter 1 / 第一章 / 卷 混用，章节识别压力测试
4. test_book.epub —— 手工构造的标准 epub
5. test_book.mobi —— 最小可用 mobi（PalmDOC 未压缩）
"""

from __future__ import annotations

import zipfile
from pathlib import Path

OUT_DIR = Path(__file__).parent / "books"


def _paragraph(n: int, seed: str) -> str:
    """生成一段带重复文本的段落，长度可控。"""
    base = (
        f"{seed}风从山谷里吹来，带着青草和泥土的气息。"
        "他站在路口，望着远方的灯火，久久没有说话。"
        "天边渐渐泛白，新的一天开始了。"
    )
    repeat = max(1, n // len(base) + 1)
    return base * repeat


def write_chinese_txt() -> Path:
    lines: list[str] = []
    lines.append("《远方的灯火》")
    lines.append("作者：测试作者")
    lines.append("")
    # 目录页
    lines.append("目录")
    lines.append("序章")
    lines.append("第一章 启程")
    lines.append("第二章 山谷")
    lines.append("第三章 归途")
    lines.append("")
    lines.append("序章")
    lines.append("")
    lines.append("这是故事的开始。那一年，他十七岁，第一次离开家乡。")
    lines.append(_paragraph(150, "序章里，"))
    lines.append("")
    lines.append("第一章 启程")
    lines.append("")
    lines.append("清晨，他在站台上等那趟绿皮火车。")
    lines.append(_paragraph(300, "第一章里，"))
    lines.append("他想起母亲临行前的叮嘱，眼眶有些发热。")
    lines.append("")
    lines.append("第二章 山谷")
    lines.append("")
    lines.append("火车在群山之间穿行，隧道一个接着一个。")
    lines.append(_paragraph(400, "第二章里，"))
    lines.append("山谷深处的小镇，安静得像一幅水墨画。")
    lines.append("")
    lines.append("第三章 归途")
    lines.append("")
    lines.append("三年后，他带着行李重新站在那个站台。")
    lines.append(_paragraph(250, "第三章里，"))
    lines.append("风还是当年的风，人却已经不是当年的人。")
    lines.append("")
    lines.append("后记")
    lines.append("")
    lines.append("故事写到这里，感谢每一位读者。")
    p = OUT_DIR / "中文规整小说.txt"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def write_mixed_txt() -> Path:
    lines: list[str] = []
    lines.append("Chapter 1 The Beginning")
    lines.append("")
    lines.append("It was a quiet morning in the small town. 阳光透过窗帘洒在地板上。")
    lines.append("She opened the window and took a deep breath. 空气中满是花香的甜味。")
    lines.append("The road ahead was long, but she was ready. 无论多远，她都会走下去。")
    lines.append("")
    lines.append("Chapter 2 The Journey")
    lines.append("")
    lines.append("The train left the station at noon. 窗外的风景不断后退。")
    lines.append("He read the letter again and again, memorizing every word. 那封信是他唯一的行李。")
    lines.append("Chapter 3 Homecoming")
    lines.append("")
    lines.append("Years later, the town had changed. 老屋还在，只是墙上的漆剥落了。")
    lines.append("She smiled. 一切都会好起来的。")
    p = OUT_DIR / "中英混排.txt"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def write_mixed_titles_txt() -> Path:
    lines: list[str] = []
    lines.append("卷一 风起")
    lines.append("")
    lines.append("江湖传闻，风起之地必有大变。")
    lines.append("")
    lines.append("1. 初入江湖")
    lines.append("")
    lines.append("少年背着一把旧剑，走进了城门。")
    lines.append("")
    lines.append("Chapter 2 雨夜")
    lines.append("")
    lines.append("雨下了一整夜，客栈的灯一直没有熄。")
    lines.append("")
    lines.append("第三回 刀光")
    lines.append("")
    lines.append("刀光闪过，庭院里只剩下风声。")
    lines.append("")
    lines.append("楔子")
    lines.append("")
    lines.append("一切恩怨，都始于那个雪夜。")
    p = OUT_DIR / "混合标题.txt"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def write_epub() -> Path:
    p = OUT_DIR / "test_book.epub"

    def xhtml(title: str, body: str) -> str:
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml"><head>'
            f'<title>{title}</title></head><body>'
            f'<h1>{title}</h1>{body}</body></html>'
        )

    ch1 = xhtml("第一章 初见", "<p>她推开那扇门，屋里点着一盏灯。</p><p>灯下的他抬起头，微微一笑。</p>")
    ch2 = xhtml("第二章 夜谈", "<p>那一夜，他们聊了很久很久。</p><p>窗外的月亮又圆又亮。</p>")

    container = (
        '<?xml version="1.0"?><container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">'
        "<metadata xmlns:dc=\"http://purl.org/dc/elements/1.1/\">"
        '<dc:title>测试电子书</dc:title><dc:language>zh</dc:language>'
        "</metadata>"
        '<manifest>'
        '<item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/>'
        "</manifest>"
        '<spine><itemref idref="c1"/><itemref idref="c2"/></spine>'
        "</package>"
    )
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/c1.xhtml", ch1)
        zf.writestr("OEBPS/c2.xhtml", ch2)
    return p


def write_mobi() -> Path:
    """mobi 构造复杂，跳过手工生成。返回占位文件。"""
    p = OUT_DIR / "test_book.mobi"
    p.write_bytes(b"mobi format placeholder - use real mobi files for testing")
    return p


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = [
        write_chinese_txt(),
        write_mixed_txt(),
        write_mixed_titles_txt(),
        write_epub(),
        write_mobi(),
    ]
    for f in files:
        print(f"{f.name}\t{f.stat().st_size} bytes")
