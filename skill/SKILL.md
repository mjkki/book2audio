---
name: book2audio
description: 将图书（epub/txt/mobi）按章节转换为带 lrc 歌词同步的 mp3 音频。当用户需要把电子书转成可听书、批量生成带歌词的章节音频、或用 edge-tts 将图书文字合成语音时使用。触发词：图书转音频、书转mp3、听书、epub转mp3、txt转语音、book2audio。
agent_created: true
---

# book2audio — 图书转音频

将图书文件按章节拆分，逐章调用微软 **edge-tts** 合成 mp3 音频，并同步生成 **lrc 歌词**（逐句时间轴）。输出 mp3 + lrc + json 三件套，便于用 MP3 播放器听书时同步显示歌词。

## 前置检查（必须先做）

1. 确认 Python 环境可用，且已安装依赖：

```bash
pip install edge-tts beautifulsoup4 lxml mutagen pydub pyyaml mobi
```

2. 确认 ffmpeg 已安装（音频拼接必需）：

```bash
ffmpeg -version   # 无输出则先安装：brew install ffmpeg
```

3. 确认 book2audio 已安装（从源码仓库克隆后，在含 pyproject.toml 的项目根目录执行 `pip install -e .`）：

```bash
book2audio --version
```

若未安装，进入源码目录执行 `pip install -e .`（注意：必须在项目根目录执行，即包含 pyproject.toml 的目录）。

> ⚠️ **`pip install -e .` 不会安装 `mobi`**：它是可选依赖，不在 pyproject 的 dependencies 里（代码内为延迟 import）。处理 `.mobi` 文件必须**额外**执行 `pip install mobi`，否则报「缺少 mobi 解析依赖，请先安装」。只做本步、跳过第 1 步的话，epub/txt 正常但 mobi 会失败。

## 第一步：选择输入文件路径（必须询问用户）

**在开始任何转换前，必须先让用户提供输入文件路径。** 直接向用户询问，明确获取：

- 图书文件路径（支持 `.epub` / `.txt` / `.mobi`，也接受 `.md` / `.azw3`）
- 确认文件存在且扩展名受支持

**绝对路径示例**（用户可能给出任意位置）：

```
~/books/某小说.mobi
~/Downloads/某小说.txt
```

## 第二步：选择输出路径（必须询问用户）

**同样必须先让用户确认输出目录。** 询问时说明：

- 输出目录不存在会自动创建
- 输出结构为 `输出目录/书名/章节文件...`
- 默认输出目录为 `./output`，但**优先使用用户指定的路径**

示例输出结构：

```text
输出目录/书名/
  01-第一章 标题.mp3
  01-第一章 标题.lrc
  01-第一章 标题.json
  ...
  manifest.json
```

## 第三步：预览章节（推荐）

转换前先 dry-run 让用户确认章节识别是否正确（避免浪费 TTS 配额）：

```bash
book2audio "<输入路径>" --out "<输出目录>" --dry-run
```

- 章节数量/标题符合预期 → 继续
- 不符合 → 用 `--chapter-pattern` 追加正则修正，或调整后重试

## 第四步：执行转换

```bash
book2audio "<输入路径>" --out "<输出目录>"
```

### 常用参数

| 参数 | 说明 |
|------|------|
| `--voice` | 音色，如 zh-CN-XiaoxiaoNeural（默认，女声）、zh-CN-YunxiNeural（男声） |
| `--rate` | 语速，如 `+10%`（快）、`-10%`（慢） |
| `--pitch` | 音调，如 `+5Hz` |
| `--resume` | 断点续跑：跳过已完成章节（中断后重跑必加） |
| `--overwrite` | 强制重跑所有章节。与 `--resume` **互斥**（argparse 互斥组），同时传入会直接报错 |
| `--dry-run` | 只解析不合成 |
| `--chapter-pattern` | 追加章节识别正则（可多次） |
| `--config` | 加载 yaml 配置文件（CLI 参数优先） |
| `--volume` | 音量，如 `+0%`、`+20%` |
| `--format` | 音频格式（默认 mp3） |
| `--segment-max-chars` | TTS 片段最大字符数（默认 500） |
| `--gap` | 片段间停顿秒数（默认 0.25） |
| `--log-level` | 日志级别 DEBUG/INFO/WARNING/ERROR |

### 完整示例

```bash
# 基本转换
book2audio "~/books/某书.epub" --out "~/books/output"

# 指定男声 + 稍快语速
book2audio "~/books/某书.txt" --out "./audio" --voice zh-CN-YunxiNeural --rate +5%

# 中断后续跑（跳过已完成章节）
book2audio "~/books/某书.mobi" --out "./audio" --resume

# 列出可用音色
book2audio --list-voices
```

## 第五步：验证结果（必须）

转换完成后向用户汇报：

1. **文件完整性**：每章 mp3/lrc/json 三件套齐全，文件名一致
2. **音频可播放**：用 ffprobe 校验 mp3 时长（`ffprobe -v quiet -show_entries format=duration -of csv=p=0 <file>`）
3. **歌词同步**：抽查 lrc 时间轴与章节时长基本吻合
4. **manifest 汇总**：读取 `输出目录/书名/manifest.json` 的 summary（ok/skipped/failed）

```bash
cat "<输出目录>/<书名>/manifest.json" | python3 -m json.tool | grep -A4 summary
```

## 关键经验与踩坑（务必遵守）

1. **网络波动已内置韧性**：默认 5 次重试 + 指数退避（2/4/8/16/30s 封顶）+ 抖动 + 连接节流（每段合成前 sleep 0.5s）。一般可自动恢复；仍失败多为并发限流（见第 7 条）。
2. **长时间任务**：大书（40+ 章）需要 30-60 分钟，400+ 章巨著可能超过 20 小时。务必以**可跨会话存活的方式**运行：终端用 `tmux`/`screen`，agent 平台用其官方后台任务机制，并持续观察日志。`nohup`/`disown` 在部分 agent 沙箱环境中会被无声回收（SIGKILL），不可靠。
3. **断点续跑**：中途中断后重跑必加 `--resume`，已完成章节（mp3/lrc/json 三件套齐全）自动跳过，不重复消耗 TTS。`--overwrite` 与 `--resume` 互斥，同时传会报错。
4. **edge-tts 是实时流式合成，勿误判卡死**：约 1x 实时速率返回音频（1.3 万字章 ≈ 44 分钟），整章 mp3 要等**全部片段拼完才落盘**。「跑了 10 分钟没出 mp3」通常正常——看日志有 `处理章节`/`完成 →` 即在推进，杀进程前务必确认日志已报错。
5. **多本务必串行**：同时跑 ≥3 本会触发 edge-tts 按 IP 限流（`Connection timeout to host wss://speech.platform.bing.com`）。一本一本跑，中断用 `--resume` 接着跑。
6. **偶发截断已自动检测重试**：基于文字长度预估时长 × 0.6 容差判定，截断片段自动重合成（默认 5 次）；全书级「实际 vs 预估」比值 < 0.7 会告警。`--dry-run` 可先打印全书预估时长预判体量。
7. **自定义章节正则**：`--chapter-pattern` 可多次追加；注意标题行 >60 字会被丢弃（会打 WARNING 日志提示）。先用 `--dry-run` 预览章节识别结果再正式转换。
8. **临时文件自动回收**：章节片段（`b2a_ch*`）与 mobi 解包目录（`mobiex*`）用完即删，带「仅限系统临时目录」护栏，无需手动清理；调试可在 config 设 `keep_segments: true` 保留片段。

> 更深层的实现细节与历史踩坑档案（edge-tts API 用法、分段器/清洗器修复记录、冒烟测试方法、页码/脚注/双重转义等文本处理细节）见源码仓库 `docs/KNOWN_ISSUES.md`。

## 故障排查

| 现象 | 处理 |
|------|------|
| 未找到 ffmpeg | `brew install ffmpeg` |
| mobi 解包失败 | 源码安装时用 `pip install -e .[mobi]` 补可选依赖；或提示用户转 epub/txt |
| 章节识别不准 | 先 `--dry-run` 预览，再用 `--chapter-pattern` 补充规则 |
| 转换中途中断 | 用 `--resume` 重跑，自动跳过已完成章节 |
| 输出目录名带乱码括号 | 属旧版残留，可提示用户删除旧目录，新转换输出干净目录 |
| **某章长时间无 mp3 但进程在跑、日志无报错** | 正常现象：edge-tts 实时合成，整章音频拼完才落盘（见踩坑第 4 条）。看日志有 `处理章节`/`完成 →` 即在正常推进，勿杀进程 |
| **多章 ConnectionTimeout 失败** | 并发限流（见踩坑第 5 条）：停止其他并发任务，改为**串行**逐本跑；已完成的章节用 `--resume` 跳过，仅重跑失败章 |
| **多章集中报 `No audio was received`，重试 5 次后章节失败** | edge-tts **服务端临时故障**（曾观测到持续约半小时的集中报错，与并发/限流无关）。等故障恢复后对同一本书加 `--resume` 重跑即可，只补失败章、已完成章自动跳过。判断依据：日志中同一错误短时间集中出现且跨多个章节 |
| **某章片段数异常多(单章 100+) 且慢/超时** | epub 行结构导致片段爆炸（详见 KNOWN_ISSUES.md B4），分段器已修复；若仍出现确认 epub 是否每行一句 |
| **部分文字没有被朗读** | 三个已知根因：① 独立数字行（年份/序号）被当页码删除；② epub 双重转义标签（`&lt;b&gt;`）内文字被吞；③ `Chapter_3` 下划线分隔的标题不识别导致正文错位。代码已修复，若再现请检查这三处：`text_cleaner._PAGE_LINE`、`epub_reader._html_to_text` 的双重转义解码、`config.chapter_pattern` 的 Chapter 正则。验证方法：抽查原文几个关键段落是否存在于章节 content 中。 |
| **某段音频中段/尾部缺失（只听到前一两句）** | edge-tts 偶发真实截断（见踩坑第 6 条）。扫描该章 json：用 `estimate_duration` 预估每段时长，凡 `实际 duration < 预估 × 0.6` 的片段即截断。代码已带重试检测；若旧产物存在，重跑该章（覆盖）即可自动修复。全书级核验：转换完成输出的「实际 vs 预估」比值 < 0.7 会有告警。 |
| **改动 TTS 客户端后合成全部报错 AttributeError** | 回归事故（详见 KNOWN_ISSUES.md B9）：重构 `edge_tts_client.py` 时曾误删 `_duration_from_words`/`_duration_from_file` 两个方法。改完核心方法后务必跑一次冒烟：导入 + 真实合成 1 个短文本，确认不报错再交付。 |
