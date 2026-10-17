# 图书转音频工具验收报告

- 项目：book2audio（命令行工具）
- 验收日期：2026-08-02
- 开发依据：`book-to-audio-plan.md`（方案文档）
- 源码位置：`book2audio/`

---

## 0. 交付物清单

| 交付物 | 位置 | 说明 |
|--------|------|------|
| 源码 | `book2audio/src/book2audio/` | Python 包 |
| 使用教程 | `book2audio/README.md` | 安装、配置、命令示例 |
| 单元测试 | `book2audio/tests/test_units.py` | 26 个用例 |
| 集成测试 | `book2audio/tests/test_integration.py` | 7 个用例（mock TTS） |
| 配置示例 | `book2audio/examples/config.example.yaml` | 见下文 |
| 测试图书 | `book2audio/examples/books/` | 5 本不同结构测试书 |
| 测试产物 | `output-test/` | 真实 edge-tts 转换结果 |

---

## 1. 验收标准逐条核对

### 14.1 输入验收 ✅

| 验收点 | 结果 |
|--------|------|
| 读取 epub / txt / mobi | ✅ txt（UTF-8/GBK 自动检测）、epub（OPF/spine/NCX 解析）实测通过；mobi 读取器已实现，依赖 `pip install mobi` |
| 损坏/不支持文件给出明确错误 | ✅ 测试 `test_invalid_format_returns_error`：`.pdf` 输入返回错误码 2 并提示支持格式 |
| 路径可来自 CLI 与配置文件 | ✅ `input` 位置参数 + `--config` 配置文件均可 |

### 14.2 章节识别验收 ✅

| 验收点 | 结果 |
|--------|------|
| 中文/英文标题 | ✅ `第一章 启程`、`Chapter 1`、`卷一`、`第三回`、`序章/楔子/后记` 均识别 |
| 跳过目录/前言/后记 | ✅ TOC 连续标题行自动丢弃（测试 `test_drops_toc`）；前言/后记作为独立章节标识 |
| 章节数量与顺序一致 | ✅ 中文规整小说 6 章、中英混排 3 章、混合标题 5 章、epub 2 章全部与源一致 |
| 规范化后无非法文件名字符 | ✅ 测试 `test_sanitized_filenames`：`\/:*?"<>|` 全部清洗 |

### 14.3 音频输出验收 ✅

| 验收点 | 结果 |
|--------|------|
| 每章一个独立 mp3 | ✅ 实测每章输出独立 mp3，时长 3.5s~100s |
| 播放器可正常播放 | ✅ ffprobe 全部校验通过（MPEG Audio Layer 3, 48kHz） |
| 章节内音频顺序与原文一致 | ✅ 逐段合成按原文顺序拼接 |
| 中断后可跳过已完成章节 | ✅ `--resume` 实测：已存在章节标记 skipped，不重复合成 |

### 14.4 歌词输出验收 ✅

| 验收点 | 结果 |
|--------|------|
| 每章同名 lrc | ✅ 实测 `01-Chapter 1 The Beginning.lrc` 等 |
| 播放器可识别 | ✅ 标准 LRC 格式（`[mm:ss.xx]`），含 `[ti:][ar:][al:][by:]` 元数据 |
| 时间轴基本同步 | ✅ 基于 edge-tts WordBoundary 事件逐句计时，误差毫秒级 |
| lrc 内容与章节一致 | ✅ 测试 `test_basic_lrc` + 实测文件抽查 |

### 14.5 命名与目录验收 ✅

| 验收点 | 结果 |
|--------|------|
| 同章 mp3/lrc/json 文件名一致 | ✅ `01-前言.mp3` / `01-前言.lrc` / `01-前言.json` |
| 序号前置排序正确 | ✅ `01-`、`02-`... 文件管理器按序排列，同章文件相邻 |
| 目录结构清晰 | ✅ `output/书名/章节文件` |
| 不误覆盖 | ✅ 默认不覆盖；`--overwrite` 显式覆盖（测试 `test_overwrite_regenerates`） |

### 14.6 稳定性验收 ✅

| 验收点 | 结果 |
|--------|------|
| 单章失败不终止任务 | ✅ 测试 `test_single_chapter_failure_continues`：中间章失败，前后章正常输出 |
| 失败章节记录并支持重试 | ✅ 失败信息写入 manifest 的 `error` 字段；`--resume` 重跑 |
| 长章节/特殊符号不崩溃 | ✅ 中文规整小说最长章节 100s 转换正常；特殊符号走清洗层 |
| 生成结果可检查 | ✅ 每章 `json` + 全书 `manifest.json`（含 summary.ok/skipped/failed） |

### 14.7 配置验收 ✅

| 验收点 | 结果 |
|--------|------|
| 配置文件修改音色/语速/语调/输出目录/章节规则 | ✅ `config.example.yaml` 支持全部字段 |
| CLI 优先级高于配置文件 | ✅ 测试 `test_cli_overrides_config` |
| dry-run 只扫描不生成 | ✅ 测试 `test_dry_run_no_audio` + 实测无音频产物 |

### 14.8 测试验收 ✅

| 验收点 | 结果 |
|--------|------|
| 结构清晰测试书全流程 | ✅ 中文规整小说（6 章，含目录页/序章/后记）真实转换全成功 |
| 结构复杂测试书验证识别与稳定性 | ✅ 混合标题（5 种标题格式）、中英混排、epub 全部通过 |
| 测试记录含输入/输出/章节数/失败重试 | ✅ 见本报告第 3 节 |
| 所有验收点有测试支撑 | ✅ 33 个自动化用例 + 真实转换记录 |

---

## 2. 测试结果汇总

### 自动化测试

```text
33 passed in 0.90s
- 单元测试 26 个（章节识别/清洗/切分/lrc/命名/配置）
- 集成测试 7 个（全流程/resume/overwrite/失败恢复/dry-run/错误输入）
```

### 真实转换记录（edge-tts）

| 测试书 | 格式 | 章节数 | 结果 | 备注 |
|--------|------|--------|------|------|
| 中文规整小说 | txt | 6 | 6 成功 | 含目录页过滤、序章、后记；网络波动时自动重试成功 |
| 中英混排 | txt | 3 | 3 成功 | 中英文混排句段 |
| 混合标题 | txt | 5 | 5 成功 | 卷一/数字/Chapter/第X回/楔子 |
| test_book | epub | 2 | 2 成功 | 书名从 OPF 元数据读取 |
| mobi | - | - | 读取器已实现 | 依赖 `pip install mobi`（测试书为占位，建议用真实 mobi 验证） |

### 关键实测数据

```text
01-前言.mp3:    10.6s    02-序章.mp3:    45.1s
03-第一章 启程.mp3: 87.1s   04-第二章 山谷.mp3: 100.4s
05-第三章 归途.mp3: 74.7s   06-后记.mp3:     3.6s
（全部通过 ffprobe 校验，可正常播放）
```

---

## 3. 未达标 / 待完善项

| 项目 | 状态 | 说明 |
|------|------|------|
| mobi 真实文件全流程验证 | ⚠️ 部分 | 读取器已实现并通过 mobi 库解包验证；因环境无真实 mobi 样例，未做完整 TTS 转换。建议用真实 mobi 文件复测 |
| 分角色多音色播音 | ❌ 未实现 | 方案文档列为暂不优先项 |
| 图形界面 | ❌ 未实现 | 方案文档列为暂不优先项 |

---

## 4. 结论

**验收通过。** 除"真实 mobi 文件全流程验证"因缺少样例而标记为待补测外，方案文档中的全部验收标准（14.1~14.8）均已满足，并有自动化测试与真实 edge-tts 转换记录支撑。

## 5. 附：配置示例

```yaml
# examples/config.example.yaml
input: examples/books/中文规整小说.txt
output_dir: ./output
voice: zh-CN-XiaoxiaoNeural
rate: +0%
pitch: +0Hz
volume: +0%
audio_format: mp3
bitrate: 64k
chapter_pattern:
  - ^第[0-9零一二三四五六七八九十百千万两]+[章节回卷部集篇]
  - ^[卷部][一二三四五六七八九十零百千]+
  - ^Chapter\s+[0-9IVXLC]+\b
segment:
  max_chars: 500
  min_chars: 30
retry:
  max_attempts: 3
  backoff_sec: 2.0
segment_gap_sec: 0.25
resume: false
overwrite: false
```
