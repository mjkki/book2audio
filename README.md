# book2audio

📖 → 🎧 **将图书按章节转换为带 lrc 歌词同步的 mp3 音频**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

基于微软 **edge-tts** 语音合成，把 `epub` / `txt` / `mobi` 图书逐章转成 `mp3 + lrc + json` 三件套——拷进任意支持歌词显示的 MP3 播放器，就能**边听书边看同步歌词**。

## ✨ 功能特性

- **多格式输入**：`epub`、`txt`（自动识别编码）、`md` / `markdown`（按 txt 处理）、`mobi` / `azw` / `azw3`（需可选依赖）
- **智能章节识别**：内置中英文常见标题规则（`第X章` / `卷一` / `Chapter 1` / `序章` / `楔子` / `后记`……），自动丢弃目录页，支持自定义正则
- **精确歌词同步**：基于 edge-tts WordBoundary 事件逐句生成时间轴，lrc 与音频毫秒级对齐
- **工业级韧性**：5 次重试 + 指数退避 + 抖动 + 连接节流；edge-tts 偶发**截断**时按「文字长度预估时长 × 容差」自动检测并重合成
- **断点续跑**：`--resume` 跳过已完成章节，中断重跑不重复消耗 TTS 配额
- **时长预判**：`--dry-run` 转换前即可预估全书音频时长；完成后输出「实际 vs 预估」对照，比值过低自动告警
- **规整输出**：`01-第一章 标题.mp3` 序号前置命名，同章三件套相邻排列，附带 `manifest.json` 全书汇总

## 📦 安装

要求：**Python 3.10+** 且系统已安装 **ffmpeg**（音频拼接必需）。

```bash
# macOS 安装 ffmpeg（其他平台用对应包管理器）
brew install ffmpeg

# 克隆并安装
git clone https://github.com/mjkki/book2audio.git
cd book2audio
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

> 需要 `mobi` / `azw3` 支持时，安装可选依赖：`pip install -e .[mobi]`

## 🚀 快速开始

```bash
# 最简单的用法
book2audio 书.txt --out ./output

# 先看看章节识别对不对（只解析不合成，附带全书预估时长）
book2audio 书.txt --dry-run

# 指定男声 + 稍快语速
book2audio 书.epub --out ./output --voice zh-CN-YunxiNeural --rate +5%

# 中断后续跑（跳过已完成章节）
book2audio 书.txt --out ./output --resume

# 列出全部可用音色
book2audio --list-voices
```

## 📂 输出结构

```text
output/
  书名/
    01-前言.mp3          # 章节音频
    01-前言.lrc          # 同步歌词（播放器自动加载）
    01-前言.json         # 逐句时间轴，方便调试与二次开发
    02-第一章 启程.mp3
    02-第一章 启程.lrc
    02-第一章 启程.json
    ...
    manifest.json        # 全书汇总：章节数、ok/skipped/failed、时长、配置
```

## 🛠 常用参数

| 参数 | 说明 |
|------|------|
| `--voice` | 音色，默认 `zh-CN-XiaoxiaoNeural`（晓晓，女声）；男声推荐 `zh-CN-YunxiNeural` |
| `--rate` | 语速，如 `+10%` / `-10%` |
| `--pitch` | 音调，如 `+10Hz` |
| `--volume` | 音量，如 `+20%` |
| `--resume` | 断点续跑（与 `--overwrite` 互斥） |
| `--overwrite` | 强制重跑所有章节（与 `--resume` 互斥） |
| `--dry-run` | 只解析章节并预估时长，不合成 |
| `--chapter-pattern` | 追加章节标题正则（可多次传入） |
| `--config` | 加载 yaml 配置文件（CLI 参数优先） |
| `--segment-max-chars` | TTS 片段最大字符数（默认 500） |
| `--gap` | 片段间停顿秒数（默认 0.25） |

配置文件示例见 [examples/config.example.yaml](examples/config.example.yaml)。

## 🤖 配合 WorkBuddy 使用（推荐）

本仓库自带一份为 AI Agent 编写的操作手册 [`skill/SKILL.md`](skill/SKILL.md)。装入 [WorkBuddy](https://www.workbuddy.cn/) 后，无需记任何命令，用自然语言即可完成转换：

```bash
# 安装 skill（复制到 WorkBuddy 用户级技能目录）
mkdir -p ~/.workbuddy/skills/book2audio
cp skill/SKILL.md ~/.workbuddy/skills/book2audio/SKILL.md
```

之后在 WorkBuddy 对话中直接说：

> 帮我把 `~/books/三体.epub` 转成音频，输出到 `~/books/output`

Agent 会按 skill 引导自动完成：**询问确认路径 → `--dry-run` 预览章节 → 执行转换 → 校验 mp3/lrc/json 三件套与 manifest 汇总**，全程无需手动敲命令。

> 该 SKILL.md 遵循通用的 Agent Skill 约定（YAML frontmatter + Markdown 正文），理论上也可用于其他支持同类约定的 agent 平台。

## 🎵 播放器推荐

把整个 `书名/` 目录拷入播放器扫描的文件夹即可，播放器会自动加载同名 `.lrc`：

- **桌面**：foobar2000（需歌词插件）、MusicBee
- **手机**：海贝音乐、网易云音乐（本地文件）、椒盐音乐
- 文件名按章节序号排序，播放列表顺序即阅读顺序

## 💡 使用小贴士

- **长书耐心等**：edge-tts 约 1x 实时速率合成，40+ 章的书需要 30-60 分钟，整章 mp3 拼完才落盘——「跑了 10 分钟没出 mp3」是正常现象，看日志有 `处理章节` / `完成 →` 即在推进
- **多本串行**：同时跑多本会触发 edge-tts 按 IP 限流，请一本一本转换
- **中断不心疼**：Ctrl+C 后重跑加 `--resume`，已完成章节自动跳过
- **章节识别不准**：先 `--dry-run` 预览，再用 `--chapter-pattern "^第.*讲"` 之类补充规则（注意标题行超过 60 字会被丢弃并打 WARNING）

## 🔧 开发与测试

```bash
# 安装开发依赖
pip install -e .[dev]

# 运行全部测试（47 个用例）
pytest tests/ -v

# 生成测试图书样本
python examples/generate_test_books.py
```

项目结构：

```text
src/book2audio/
  cli.py                # 命令行入口
  config.py             # 配置加载（默认值/文件/CLI 三级）
  converter.py          # 转换编排（章节 → 音频 → 歌词）
  models.py             # 数据模型（Book/Chapter/Segment）
  reader/               # 图书读取（txt/epub/mobi）
  parser/               # 章节识别、文本清洗、句子切分
  tts/                  # edge-tts 合成、音频拼接、时长预估
  subtitle/             # lrc 生成
  output/               # 命名规范、manifest
```

## 📚 文档

- [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) — 实现细节与踩坑档案（edge-tts API 用法、截断检测原理、文本清洗规则、冒烟测试方法等）
- [skill/SKILL.md](skill/SKILL.md) — AI Agent 操作手册
- [ACCEPTANCE.md](ACCEPTANCE.md) — 验收报告

## ❓ 故障排查

| 现象 | 处理 |
|------|------|
| `未找到 ffmpeg` | 安装 ffmpeg（macOS：`brew install ffmpeg`） |
| `缺少 mobi 解析依赖` | `pip install -e .[mobi]`，或先把 mobi 转成 epub/txt |
| 章节识别不准 | `--dry-run` 预览 → `--chapter-pattern` 补充正则 |
| 转换中途中断 | 加 `--resume` 重跑，已完成章节自动跳过 |
| 某章长时间无 mp3 | 正常现象（实时合成），看日志确认在推进即可 |
| 多章 ConnectionTimeout | 并发限流，停止其他任务改串行，`--resume` 补失败章 |
| 多章报 `No audio was received` | edge-tts 服务端临时故障，稍后 `--resume` 重跑 |

## 📄 许可证

[MIT License](LICENSE) © 2026 mjkki
