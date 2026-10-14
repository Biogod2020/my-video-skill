# 课程音频时间轴与对齐基准规范

本规范定义课程母带音频的时间轴提取、双语对齐、停顿补白与安全剪辑候选生成流程。时间戳由声学识别/对齐模型提供，波形测量与切点筛查由工程脚本执行（`llm_timing_calls=0`）；Gemini/agy 不推测词秒或裁决静音阈值。本步骤只导出候选，母带保持不变（`audio_modified=false`）。

## 1. 核心原则与职责分工

- **确定性工程底座**：字词时间戳、波形能量（RMS/Peak）、静音区间与 sample 级候选切点由专用对齐模型与音频脚本测量。
- **教学意图标注**：在 agy 撰写讲稿阶段通过元数据声明停顿诉求（如 `after_quote`、`purpose` 及可选 `target_gap_seconds`），作为下游候选生成的参数，不作为自动化裁决依据。
- **母带修改闭环**：候选文件仅标记可切点时间戳而非删除范围（`edit_approved=false`）。只有在生成 sample-level EDL 并实际修改音频后，才重映射字幕与章节，新完整音频由 Gemini 实际听审，新完整 MP4 由 Gemini 实际视听审核。当前阶段母带未改动，不执行虚假多模态审核。

## 2. 已实测双语对齐链路

### 中文逐字对齐（Qwen ForcedAligner）
中文采用 Qwen ForcedAligner 提取逐字（CJK 字符及 Latin/数字单元）绝对时间戳。旧 ASR 仅用于规划小于 180 秒的上下文窗口，不切碎母带实体，亦不作为精度金标准。

1. **数据准备**：
```bash
python scripts/prepare_qwen_alignment.py \
  --audio PCM16mono.wav \
  --lesson lesson.json \
  --coarse-alignment exact-hash.asr.json \
  --out private/kit
```
剔除不发音的标记（如 `[pause Xs]`），保留真实口播串。本机候选导出安装 `scripts/timeline-requirements.txt`；GPU 推理使用独立 Python 3.11 环境，安装 `scripts/timeline-gpu-requirements.txt`（含固定 Git commit），不将 CUDA 依赖装进本机剪辑环境。环境锁定：模型权重 `c7cbfc2048c462b0d63a45797104fc9db3ad62b7`，代码 `7c6daf77a2421100f5fb066495372c00129d39ff`，`qwen-asr==0.0.6`，`transformers==4.57.6`，GPU PyTorch 2.8.0 / torchaudio 2.8.0（SDPA, BF16）。

2. **推理与重组**：
```bash
python scripts/run_qwen_alignment.py --kit private/kit --out aligned
# 或使用历史原生输出验证重放：
python scripts/run_qwen_alignment.py --kit private/kit --assemble-only --results prior-native-outputs --out aligned
```
保留原生与修正时间戳并记录 `repaired_timestamp` 标识。实测 B02 口播（3186 native units，含 3146 CJK 字符与 40 组 Latin/数字）检出 15 处零时长与 6 处修正。Qwen 原生不输出置信度，严禁虚构分数或线性插值零时长。

### 英文逐词对齐（Global CTC）
英文保留全局 CTC：带上下文的声学窗口提取共享帧网格，再求一次全局路径，不按单句独立对齐：
```bash
python scripts/align_global_ctc.py \
  --audio PCM16mono.wav \
  --text spoken.txt \
  --out narration.ctc.json
```
使用 torch/torchaudio 2.8。已有结果的母带哈希与口播 token 流匹配时，直接重用其词秒，无需重新推理（本轮保留 2097 个 CTC 词）。

本轮集成复用前轮已完成的中文 GPU 原生结果并验证重放，没有再跑一次 GPU 推理；英文直接保留同母带 CTC 结果。

## 3. 时间轴映射与候选生成

通过对齐产物与讲稿生成结构化时间轴映射：
```bash
python scripts/build_text_audio_map.py \
  --language zh \
  --audio PCM16mono.wav \
  --alignment aligned/qwen.units.json \
  --lesson lesson.json \
  --policy scripts/course-timeline-policy.json \
  --out timeline/
```
复制 `scripts/course-timeline-policy.json` 到课程目录，填入 agy 已写的 `boundaries`（`after_quote`、`purpose`、可选 `target_gap_seconds`）；重复引文用 1-based `occurrence` 明确位置。默认空清单只出结构提示，不自动设定每句停顿目标。英文使用同一命令的 `--language en` 与已验证 CTC 文件。

- **校验机制**：严格校验冻结口播文本与对齐单元的 token 流。强制对齐不证明音频念全或念对，漏读、重复与错读仍由独立 ASR 和实际听审核对。段落末尾及教学标点生成切点候选提示，普通逗号不是默认切点；`protected_phrases` 保护术语完整性；若相邻存在低分、零时长、时间戳修正或区间 overlap，自动阻断候选生成；空分保持 null。
- **波形检验**：结合 RMS、Peak 及静音保护窗口进行纯静音与近零样本（near-zero sample）扫描。波形 quiet 不等于绝对无呼吸，需保留人工听感复核；已有停顿达到 `target_gap_seconds` 时不触发补白。
- **生成产物**：输出 `word-seconds.csv`、`text-audio-map.json`、`boundary-candidates.csv`、`timestamped-script.md`、`pause-candidates.json` 与 `safe-edit-candidates.json`。输出明确区分待复听、待语义审查、已有留白足够及不合格边界，均为 `edit_approved=false`。

## 4. 句级 ASR 与段落剪辑路线

对于无需逐字定位或第三方提供的句段转录，采用通用候选提取工具：
```bash
python scripts/build_segment_edit_candidates.py \
  --audio PCM16mono.wav \
  --segments transcription.json \
  --out segment-candidates.json
```
- **数据协议**：标准输入必须包含 `source_sha256` 及以秒为单位的 `segments[{start, end, text}]`。若原生 API 使用毫秒或其它键名，须通过显式 adapter 转换，**严禁将句段总时长按字数平均拆分虚构词秒**。
- **剪辑逻辑**：仅在句段间结合波形静音与保护窗标记候选切点，不自动裁切呼吸或压缩停顿，默认对齐方式仍为中文 Qwen 与英文 CTC。
- **前沿 ASR 特性参考（本轮未跑新模型实测对比，以下基于官方文档）**：
  - [VibeVoice-ASR](https://github.com/microsoft/VibeVoice)：支持 60 分钟长音频转录与角色/句段切分，适合超长课件的宏观结构定位。
  - [Parakeet TDT 0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)：提供 25 种欧洲语言（含英文，不含中文）的高速词级/句级时间戳。
  - [Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR)：提供识别文本，细时间戳由独立 ForcedAligner 模块提供。
  - [FunASR](https://github.com/modelscope/FunASR/blob/main/docs/python_api.md)：SenseVoice + FSMN-VAD 流水线可提供 `sentence_info` 段时间；可选字词时间戳与 `fa-zh` 须按具体模型、接口分别核实。
- **推荐工作流**：粗粒度 ASR 确定句段范围 -> 纯波形静音带确定初剪点 -> 仅在边界歧义时调用精细强制对齐。
