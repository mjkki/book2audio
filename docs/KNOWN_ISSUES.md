# KNOWN_ISSUES — 实现细节与踩坑档案

本文档沉淀 book2audio 开发过程中验证过的实现细节、已修复缺陷与排查方法，供贡献者与维护者参考。日常使用中最常见的操作要点见 README 与 SKILL.md。

---

## A. 核心实现要点

### A1. edge-tts 7.x API 用法
`Communicate(text, voice, boundary="WordBoundary")` + `stream()` 收集 WordBoundary chunk 获取逐句时间轴（offset/duration 单位 100ns，除以 1e7 得秒）。

### A2. ffmpeg concat 必须用绝对路径
concat demuxer 按 list 文件所在目录解析相对路径，相对路径会找不到文件。`tts/audio.py` 已统一 `resolve()`。

### A3. argparse help 文本中的 `%`
含 `%` 需写成 `%%`，否则 `--help` 崩溃。`cli.py` 中 `--rate`、`--volume` 的 help 均已处理。

### A4. mobi8/KF8 解包产物
`mobi.extract()` 对新格式返回的是 **epub** 而非 HTML，`reader/mobi_reader.py` 自动检测后缀并复用 epub 解析。

### A5. epub 封面/目录页过滤
内容 <40 字且无句末标点的块自动过滤；含 `Content/Chapter_X/目录` 导航特征且无句号的短块也会过滤（`reader/epub_reader.py`）。

---

## B. 健壮性设计（网络与长任务）

### B1. 网络波动韧性
edge-tts 偶发 SSL 卡死或连接超时。`tts/edge_tts_client.py` 默认 5 次重试 + 指数退避（2/4/8/16/30s 封顶）+ 抖动 + 连接节流（每段合成前 sleep 0.5s 降连接速率）。一般可自动恢复；仍失败多为并发限流（见 B6）。

### B2. 长时间任务
大书（40+ 章）需要 30-60 分钟，400+ 章巨著可能超过 20 小时。务必以可跨会话存活的方式运行（终端用 `tmux`/`screen`；agent 平台用其官方后台任务机制）。注意 `nohup`/`disown` 在部分 agent 沙箱环境中会被无声回收（SIGKILL），不可靠。中断后加 `--resume` 续跑。

### B3. 断点续跑
中途中断后重跑必加 `--resume`，已完成章节自动跳过（要求 mp3/lrc/json 三件套齐全且 mp3 非空），不重复消耗 TTS 配额。`--overwrite` 与 `--resume` 在 CLI 层面互斥（argparse mutually exclusive group），同时传入会直接报错。

### B4. 片段爆炸致连接耗尽（已修复）
部分 epub 正文是「每行一句」（句间 `\n` 而非空行分段）。旧分段器把每个换行当段落边界，导致单章切成 100+ 个微型片段（1.3 万字章曾切成 166 段、平均 79 字），单章开 100+ 个 WebSocket → 耗尽 edge-tts 按 IP 的连接额度，后续章节 ConnectionTimeout。

**修复**：`parser/segmenter.split_chapter` 改为按空行分段、段内换行合并为空格（同章 166→28 段，连接数降 6 倍）。若某章持续 ConnectionTimeout，先确认该 epub 行结构是否异常。

### B5. edge-tts 是实时流式合成，勿误判卡死
edge-tts 按 ~1x 实时速率返回音频：~480 字片段 ≈ 90–97 秒音频；1.3 万字章 ≈ 44 分钟。整章 mp3 要等**全部片段拼完才落盘**，「跑了 10 分钟没出 mp3」通常是正常合成中——看日志是否有 `处理章节：第X章`（章开始）和 `完成 →`（章结束）。杀进程前务必确认日志已报错（ConnectionTimeout/RuntimeError）。

> 本条秒数是**实测合成耗时**，与 B8 的预估模型（0.235s/字）**不是同一口径**：480 字按预估为 480×0.235≈113s，实测 90–97s，实测约为预估的 0.85（全书级约 0.93）。做截断判定时以预估模型为准。

### B6. 多本并发会触发限流，务必串行
同时跑 ≥3 本书时，后启动的章节集中出现 `Connection timeout to host wss://speech.platform.bing.com`（按 IP 限流）。正确做法：**一本一本串行跑**；配合 B4 的少片段，串行几乎不会再限流。中断后加 `--resume` 续跑。

### B7. edge-tts 偶发「真实截断」及检测机制
edge-tts 会间歇性返回被截断的 mp3——音频只到中段/尾部，且对应 WordBoundary words 也只到一半（非确定性：同一文本重合成可能正常 30s，也可能偶发 17s）。

**现行检测**（`edge_tts_client._assert_not_truncated`）：
- 判定真值取**真实 mp3 文件时长**（mutagen 读 `MP3().info.length`）；不要用 WordBoundary words 时长——words 偶尔丢尾词但音频完整，据此判会误杀好音频
- 用 `tts/duration_estimator.estimate_duration` 按字符类型加权预估（CJK 0.235s/字、拉丁词 0.32s/词、符号 0.10s/个，`rate` 自动缩放）
- 实际时长 < 预估 × 0.6（`truncation_tolerance`，config `duration_estimate` 可调）即抛 RuntimeError 触发重试（默认 5 次）
- 跳过校验条件：`char_weight` 的 `cjk + latin_words < 15`（标点不计入），短片段阈值不可靠故不校验
- 实测精度：387 字段落预估 90.9s vs 实际 91.1s；全书 20.9 万字预估 11.8h vs 实际 11.0h（比值稳定 ~0.93，远高于容差，不误杀）

### B8. 时长预估的三处生效点
`tts/duration_estimator.py`：① 每片段合成后截断校验（见 B7）；② `--dry-run` 打印全书预估音频时长；③ 转换完成打印「实际 vs 预估」对照（口径=非失败章节），实际 < 预估 70% 告警。系数与容差在 config `duration_estimate` 可调；换音色后若实际/预估比偏离 0.93 太多，可按实测重调 `per_cjk_char`。`_parse_rate` 已防御 `-100%` 除零。

### B9. 改动 TTS 核心客户端后必须冒烟测试
`edge_tts_client.py` 的 `synthesize`/`_once`/`_duration_from_words`/`_duration_from_file`/`_assert_not_truncated` 是合成主链路，任何一处签名或方法缺失都会让**整本书所有片段失败**（曾误删两个方法导致每次 synthesize 都抛 AttributeError）。改完务必跑：

```bash
python3 -c "from pathlib import Path; from book2audio.tts.edge_tts_client import EdgeTTSClient; EdgeTTSClient().synthesize('这是一段用于冒烟测试的中文文本，长度需超过十五字才会触发截断校验', Path('/tmp/t.mp3'))"
```

确认不抛异常；并跑 `pytest tests/`（47 项）确认回归。

> **跑测试报 `PermissionError: EEXIST ... pytest-of-unknown` 时别慌**：部分受限执行环境（沙箱）对已存在的 pytest 临时目录做 `mkdir` 时按 EEXIST 抛错（正常 pytest 会忽略）。绕法：`pytest tests/ -q --basetemp=/tmp/b2a_pytest_run`。

---

## C. 文本处理细节（防止吞字）

### C1. 页码过滤勿误删正文数字
正文中的独立数字行（年份 1945/2024、列表序号 1、正文数字 35）是真实内容，必须朗读！只有「第 X 页」「- 12 -」「(23)」这类真实页码格式才删除（`parser/text_cleaner._PAGE_LINE`）。

### C2. 双重转义标签
部分出版方把 `<b>` 写成 `&lt;b&gt;`（再转义一次），清洗后若未解码，标签内文字会被吞掉不朗读。`epub_reader._html_to_text` 必须先将 `&lt;`/`&gt;` 解码两次让标签恢复真实结构。

### C3. Chapter 标题分隔符多样
章节标题可能是 `Chapter 3`（空格）、`Chapter_3`（下划线）、`Chapter.3`、`Chapter:3`。正则须用 `^Chapter[\s_.:-]+[0-9IVXLC]+` 兼容所有分隔符，否则下划线格式标题不识别会导致后续正文被错误归并/吞掉。

> **自定义 `--chapter-pattern` 注意**：`chapter_detector._MAX_TITLE_LEN = 60`，正则命中但超 60 字的行会被丢弃（**会打 WARNING 日志**，不再静默）。典型症状：「正则写对了、dry-run 里却完全没生效」→ 先看日志是否提示超长。

### C4. 正文编号列表勿当标题
正文中「1. 现代集团对汽车产业的期望很高」这类编号列表行不是章节标题，误判会吞掉该行文字。数字编号格式仅在行较短（≤20 字）**且无句号/非脚注**时才视为标题（「1. 美国俄亥俄州。——译者注」这类脚注不当标题）。

### C5. 转换后完整性验证
对比原始文本与章节内容，抽查几个关键段落是否存在于章节 content 中，确认正文段落零丢失。

### C6. 书末目录/索引残留
部分 epub 书末有目录索引页，会被切成分章节（内容仅「目录」两字且标题与前面章节重复）。`_drop_duplicate_tail` 会丢弃「标题已出现过且内容 <10 字」的章节。

### C7. 脚注并入正文
epub 的脚注（译者注等）通常排在章节末尾，会被 `^\d+\.` 规则误判为独立章节。已通过「句号结尾/含译者注不当标题」修复，脚注内容会正确并入所属章节朗读。

---

## D. 资源管理

### D1. 临时片段目录自动回收
每章临时片段写入系统临时目录（`b2a_ch*` 前缀），拼接完成后由 `converter._cleanup_segments` 自动删除（无论成功失败，finally 中执行）。护栏：仅当目录位于系统临时目录下且带 `b2a_ch` 前缀时才删除。调试时可在 config 设 `keep_segments: true` 保留片段。

> 历史问题：旧版 `_cleanup_segments` 为空实现，大批量转换（~340h 音频量级）曾累积 7.9G/1166 个临时目录，需手动清理。已修复。

### D2. mobi 解包目录自动回收
`mobi.extract()` 自建 `mobiex*` 临时目录且库本身不清理。`mobi_reader` 在 `finally` 中回收，并带「仅限系统临时目录下」护栏防止误删用户文件。回归测试见 `tests/test_units.py::TestMobiTempCleanup`。
