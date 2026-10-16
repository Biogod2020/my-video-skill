# 课程音频时间轴与对齐基准规范

本规范定义课程母带音频的时间轴提取、双语对齐、停顿补白派生与时间轴重映射的标准流水线。时间戳由声学对齐模型提取，波形测量、静音检测、补差切点计算与 EDL 生成全部由确定性工程脚本执行（`llm_timing_calls=0`）；Gemini/agy 负责在讲稿中声明教学停顿意图并进行最终全量实听实看，严禁大模型推测词秒或裁决静音阈值。全课程默认采用“连续原生语音生成 -> 冻结母带 -> 确定性对齐与候选分析 -> 按语言规则生成 EDL 重映射音频/字幕/画面/章节 -> Gemini 独立实听完整新音频与实看新 MP4 -> 用户预览/发布”闭环；时间轴提取与候选分析默认执行无需每课重复征询授权。停顿剪辑应用按语言明确分流：中文保留既有 `annotated_boundaries` 默认应用（不改其既有工程方式，亦不鼓励机械补白）；英文根据用户最新反馈更新默认规则，整轨默认保留原生停连和语流，工程默认 `application_mode=candidates_only`，输出零 edits identity EDL（音频原 PCM 逐样本不变，仍统一驱动字幕/画面）；英文仅在显式配置 `application_mode=necessary_only` 且边界满足严格必要性（`necessary_edit:true` 与非空 `necessity_reason`）时才应用剪辑，已有自然停顿足够或不补更连贯时允许全课 0 次剪辑。

## 1. 核心原则与默认执行闭环

- **确定性工程底座**：字词时间戳、波形能量（RMS/Peak）、纯静音与近零样本区间由专用对齐模型与音频脚本测量，杜绝大模型猜测时间戳。
- **教学意图标注与 Policy 约束**：在 agy 撰写讲稿阶段通过元数据声明句末停顿诉求（如 `after_quote`、`purpose` 及可选 `target_gap_seconds`），各课程通过独立的 policy 配置文件声明补白目标与安全上限，作为工程剪辑的输入参数。严禁硬编码每句话补白或在所有课程中固定4处；历史 B02 采用的最多4处语义点、每点最多0.45秒为实测认可的试验参考（中文最终4处1.74秒，英文最终3处0.95秒），但后续英文规则已被当前用户偏好更新：用户明确反馈英文版加入人工断句反而不顺，整轨默认保留原生停连和语流，不能按句号、换页、所谓认知点或固定秒数补齐。旧 policy 中的 `target_gap_seconds`、`[pause Xs]` 或语义意图标注不再自动授权英文补足，英文亦不接受 `annotated_boundaries` 批量套用；对齐和候选分析虽仍为全课默认，但英文工程应用模式默认设为 `application_mode=candidates_only`，输出零 edits identity EDL（原 PCM 逐样本不变，仍统一驱动字幕/画面）；仅在显式声明 `application_mode=necessary_only` 且边界逐一标有 `necessary_edit:true` 与非空 `necessity_reason`（例如问句确实抢入答案、听众确实来不及看关键图，经真实前后音频复核确有缺口且通过波形静音检查）时才允许剪辑，已有自然停顿足够、不补更连贯、无明确问题时允许全课 0 次剪辑。中文原有 `annotated_boundaries` 默认保留，同样不鼓励机械补白，但本次不改变其中文既有默认工程应用方式。
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

由确定性剪辑脚本执行停顿处理与时间轴重映射。工程接口支持通过 `application_mode_by_language` 显式声明语言默认行为：中文默认保留 `annotated_boundaries` 应用；英文默认设为 `application_mode=candidates_only`（输出零 edits identity EDL、音频原 PCM 逐样本不变，仍统一驱动字幕/画面；仅当显式指定 `application_mode=necessary_only` 且存在经前后音频复核确有必要、标注 `necessary_edit:true` 与非空 `necessity_reason` 的边界时才执行剪辑）：
```bash
python scripts/apply_course_timeline_pauses.py \
  --language zh \
  --audio PCM16mono.wav \
  --alignment aligned/qwen.units.json \
  --lesson lesson.json \
  --policy course-pause-policy.json \
  --out narration/
```
英文对应使用 `--language en` 与 `--alignment narration.ctc.json`（默认 `application_mode=candidates_only`；若需必要剪辑则传入配有 `necessary_edit: true` 与 `necessity_reason` 的 policy 并在 policy JSON 中设置 `application_mode=necessary_only`）。

- **工程产物标准**：
  1. `narration.wav`：插入稀疏小补白后的派生母带音频。
  2. `narration.json`：派生母带元数据（时长、音频属性与补白摘要）。
  3. `alignment.json`：依据插入点平移校正后的最新逐字/逐词对齐结果。
  4. `pause-edl.json`：精确到采样的编辑决策列表（sample-level EDL），记录插入切点、原采样偏移与插入采样数。
  5. `remap.json`：源母带秒数与派生秒数之间的映射表，向下游导出支持毫秒级源秒溯源与音画对齐。
- **原 PCM 逐样本相等验证**：工程脚本必须对比原母带与派生母带在未补白区间的波形数据，严格满足逐样本一致（sample-exact identity），确保音频无任何重新编码损耗、无重采样、无滤波与无音色篡改。
- **全流程同步重映射**：画面分镜关键帧、字幕 SRT/VTT、章节标记和片尾预留统一基于同一份 `pause-edl.json` / `remap.json` 平移，确保音画字严格对齐。
- **独立实听实看闭环**：派生文件生成导致 hash 变更后，严禁复用原生母带的通过状态。导出的完整 `narration.wav` 必须送交 Gemini/agy 独立全量实听；最终合成的完整 MP4 必须送交 Gemini/agy 独立全量视听审核，实审通过且记录回执后方可发布。

- **题前思考留白与边界级配置规范**：`apply_course_timeline_pauses.py` 支持在单个边界级别配置 `maximum_added_seconds`，以覆盖该课程全局的 `maximum_added_seconds_per_point`。此接口用于必要时精细控制停顿，但严禁盲目自动套用：
  - **英文严格废除自动转换 [pause 4s] 补齐**：旧流程中“直接读取既有 `[pause 4s]` 等元数据自动转换为 `target_gap_seconds=4` 补足”的规则在英文版中彻底废止。英文旧 policy 的 `target_gap_seconds`、`[pause Xs]` 或语义标注不再自动授权补足；讲稿出现“Pause your screen”亦绝不代表必须强塞长静音。英文题前可按需补白，但不自动把所有题补到 4 秒；必须在 `application_mode=necessary_only` 下由边界显式声明 `necessary_edit:true` 与非空 `necessity_reason`，且必须经实际前后音频复核证明存在真实抢入/缺口并满足波形静音安全检查，已有原生留白足够或不补更连贯时严禁剪辑（例如 B-01 英文原生母带 433.04 秒，原生题前间隔已有 3.22s/1.02s，后期仅补 0.78s/2.98s 到固定 4 秒；用户反馈加入人工断句后不顺，故先回滚作对照）。
  - **中文既有方式保持**：中文原有 `annotated_boundaries` 默认保留，同样不鼓励机械补白，但本次不改其中文既有默认工程应用方式。
  - **LLM 职责与审核底线**：LLM 严禁估算精确词秒或静音阈值，不增加 LLM 数值审批或每次重复征询用户授权；最终导出的新音频与新完整 MP4 仍由 Gemini 全量实听实看并给出语流自然度证据，但用户反馈高于模型 PASS。
  - **听感问题排查与回滚原则**：听感不顺成立不能反推所有长气口都是后期造成；遇到问题时必须先调取 EDL 区分后期插入静音与原生气口。若属后期剪辑引入问题则优先回滚；若属原生过长停顿，应明确“原生”不代表“天然自然”，经实听确认的原生过长静音可按需缩短，保护的是发声和呼吸而非冻结所有原生空隙，具体审计流程与工程裁剪详见 [references/english-gap-audit.md](english-gap-audit.md)；严禁无证据全盘裁减，严禁通过重新生成 TTS 修复仅由静音引起的问题；完整保留原版与新派生版，经用户审核确认后再更新公开视频。

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
