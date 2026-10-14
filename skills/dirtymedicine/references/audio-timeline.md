# 课程音频时间轴与对齐基准规范

本规范定义课程母带音频的时间轴提取、双语对齐、停顿补白派生与时间轴重映射的标准流水线。时间戳由声学对齐模型提取，波形测量、静音检测、补差切点计算与 EDL 生成全部由确定性工程脚本执行（`llm_timing_calls=0`）；Gemini/agy 负责在讲稿中声明教学停顿意图并进行最终全量实听实看，严禁大模型推测词秒或裁决静音阈值。所有课程默认采用“连续原生语音生成 -> 冻结母带 -> 确定性对齐与句末意图标注 -> 工程静音保护与补差 -> 同一 sample EDL 重映射音频/字幕/画面/章节 -> Gemini 独立实听完整新音频与实看新 MP4 -> 用户预览/发布”闭环；默认执行无需每课重复征询用户留白授权。

## 1. 核心原则与默认执行闭环

- **确定性工程底座**：字词时间戳、波形能量（RMS/Peak）、纯静音与近零样本区间由专用对齐模型与音频脚本测量，杜绝大模型猜测时间戳。
- **教学意图标注与 Policy 约束**：在 agy 撰写讲稿阶段通过元数据声明句末停顿诉求（如 `after_quote`、`purpose` 及可选 `target_gap_seconds`），各课程通过独立的 policy 配置文件声明补白目标与安全上限，作为工程剪辑的输入参数。严禁硬编码每句话补白或在所有课程中固定4处；B02 采用的最多4处语义点、每点最多0.45秒为实测认可的试验参考（中文最终4处1.74秒，英文最终3处0.95秒），后续课程按各自 policy 动态管理。
- **严格安全剪辑边界**：切点必须落在波形平直的确定性静音带上；严禁在词内、主谓之间或尚未揭晓答案的引导句间切；已有自然停顿达到 `target_gap_seconds` 时自动跳过；保持原生音色与自然重音，默认无全局 atempo、无逐句 R3 时间拉伸、无逐逗号自动静音标准化。
- **对齐异常阻断**：Qwen 遇到零时长、时间戳修正或区间 overlap 时，邻界自动阻断补白候选生成；Qwen 原生不输出置信度，严禁虚构分数或对零时长进行线性插值；强制对齐不证明发音内容完全正确，漏读、重复与错读仍需依赖独立 ASR 和听审把关。
- **派生母带闭环验证**：由脚本输出派生母带与 sample-level EDL，必须通过非补白区间原 PCM 逐样本相等验证（sample-exact identity）；同一 EDL 同时重映射音频、字幕、画面与章节；派生音频 hash 改变后，严禁复用旧母带审核结论；新完整音频必须由 Gemini 独立全量实听，新完整 MP4 必须由 Gemini 独立全量视听审核，用户预览确认后方可发布。

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
保留原生与修正时间戳并记录 `repaired_timestamp` 标识。Qwen 原生不输出置信度，严禁虚构分数或线性插值零时长；对齐单元若存在零时长或时间修正，其边界候选自动设为阻断。

### 英文逐词对齐（Global CTC）
英文保留全局 CTC：带上下文的声学窗口提取共享帧网格，再求一次全局路径，不按单句独立对齐：
```bash
python scripts/align_global_ctc.py \
  --audio PCM16mono.wav \
  --text spoken.txt \
  --out narration.ctc.json
```
使用 torch/torchaudio 2.8。已有结果的母带哈希与口播 token 流匹配时，直接重用其词秒，无需重新推理。英文同样保持整轨全局路径，不切碎母带独立对齐。

## 3. 时间轴映射与候选生成

通过对齐产物与讲稿生成结构化时间轴映射及安全切点候选：
```bash
python scripts/build_text_audio_map.py \
  --language zh \
  --audio PCM16mono.wav \
  --alignment aligned/qwen.units.json \
  --lesson lesson.json \
  --policy course-pause-policy.json \
  --out timeline/
```
复制 `scripts/course-timeline-policy.json` 到课程目录，显式填写正数 `maximum_added_seconds_per_point`，并按各标注设置 `target_gap_seconds`；再填入 agy 已写的 `boundaries`（`after_quote`、`purpose`、可选 `target_gap_seconds`）；重复引文用 1-based `occurrence` 明确位置。英文使用同一命令的 `--language en` 与已验证 CTC 文件。

- **校验机制**：严格校验冻结口播文本与对齐单元的 token 流。段落末尾及教学标点生成切点候选提示，普通逗号不是默认切点；`protected_phrases` 保护术语完整性；若相邻存在低分、零时长、时间戳修正或区间 overlap，自动阻断候选生成；空分保持 null。
- **波形检验**：结合 RMS、Peak 及静音保护窗口进行纯静音与近零样本（near-zero sample）扫描。波形 quiet 不等于绝对无呼吸，需保留人工听感复核；已有停顿达到 `target_gap_seconds` 时不触发补白。
- **生成产物**：输出 `word-seconds.csv`、`text-audio-map.json`、`boundary-candidates.csv`、`timestamped-script.md`、`pause-candidates.json` 与 `safe-edit-candidates.json`。输出明确区分待复听、待语义审查、已有留白足够及不合格边界。

## 4. 自动化稀疏留白与时间轴重映射

由确定性剪辑脚本自动应用符合教学标注与波形静音规则的稀疏小补白：
```bash
python scripts/apply_course_timeline_pauses.py \
  --language zh \
  --audio PCM16mono.wav \
  --alignment aligned/qwen.units.json \
  --lesson lesson.json \
  --policy course-pause-policy.json \
  --out narration/
```
英文对应使用 `--language en` 与 `--alignment narration.ctc.json`。

- **工程产物标准**：
  1. `narration.wav`：插入稀疏小补白后的派生母带音频。
  2. `narration.json`：派生母带元数据（时长、音频属性与补白摘要）。
  3. `alignment.json`：依据插入点平移校正后的最新逐字/逐词对齐结果。
  4. `pause-edl.json`：精确到采样的编辑决策列表（sample-level EDL），记录插入切点、原采样偏移与插入采样数。
  5. `remap.json`：源母带秒数与派生秒数之间的映射表，向下游导出支持毫秒级源秒溯源与音画对齐。
- **原 PCM 逐样本相等验证**：工程脚本必须对比原母带与派生母带在未补白区间的波形数据，严格满足逐样本一致（sample-exact identity），确保音频无任何重新编码损耗、无重采样、无滤波与无音色篡改。
- **全流程同步重映射**：画面分镜关键帧、字幕 SRT/VTT、章节标记和片尾预留统一基于同一份 `pause-edl.json` / `remap.json` 平移，确保音画字严格对齐。
- **独立实听实看闭环**：派生文件生成导致 hash 变更后，严禁复用原生母带的通过状态。导出的完整 `narration.wav` 必须送交 Gemini/agy 独立全量实听；最终合成的完整 MP4 必须送交 Gemini/agy 独立全量视听审核，实审通过且记录回执后方可发布。

- **题前思考留白与边界级上限覆盖**：`apply_course_timeline_pauses.py` 支持在单个边界级别配置 `maximum_added_seconds`，以覆盖该课程全局的 `maximum_added_seconds_per_point`。此接口专门用于兑现原讲稿中明确声明的较长题前思考停顿，与机制解释段落的稀疏小补白严格区分（非所有课程固定 4 秒，依讲稿声明配置）。工程流水线直接读取既有 `[pause 4s]` 等题前元数据确定性转换为 `after_quote` + `target_gap_seconds=4` + `maximum_added_seconds=4`，严禁由 LLM 推测秒数；多道练习题出现相同引文时，通过 1-based `occurrence=1`、`2` 唯一定位。普通 0.5s 等过渡标记不逐个自动补白；若原有波形静音已达到目标则自动跳过；题前思考停顿与机制补白统一汇入同一份 sample-level EDL 一次性完成音画与字幕重映射。

## 5. 句级 ASR 与段落剪辑路线

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
