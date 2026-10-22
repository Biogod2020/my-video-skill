# 初学者复述审核与全库逐段对照规范

本规范规定医学教学讲稿在进入配音与成片前必须通过的教学质量验收标准。本规范旨在建立可检查、可追溯的模型角色教学审核证据，防范脱离认知规律与缺少因果推导的盲目通过。

---

## 1. 有效输入版本与私有对照库管理

1. **实时有效输入版本原则**：
   - 每次调用前，必须实时读取当前工作区最新的 `SKILL.md` 及相关 references，记录其实际版本与文件内容哈希。
   - 历史 dossier 或任务包中固化的 skill 历史快照（如旧版 2.8 等）绝对不得覆盖当前生效规则。
   - 发现输入材料中的 skill 规则与当前环境冲突时，必须先刷新实际输入再执行任务，严禁在喂给模型旧规则的情况下声称已执行新规范。
2. **动态基准对照库（覆盖全部已登记同语种前课）**：
   - 讲稿改写或新写必须与既往所有已获用户明确认可的同语种课程进行全文对照。随着项目推进，对照库持续动态增长，审核必须覆盖当前清单登记的全部同语种前课，严禁仅挑单课或抽象背书。
   - **当前登记基准课**（中文 4 份、英文 3 份，动态追加）：
     - 中文正例：G6PD缺乏症（B09）、果糖代谢障碍（B11）、夜间禁食血糖维持：糖原分解与糖异生（B02 中文版）、B01 已获用户认可的简明中文版。
     - 英文正例：G6PD Deficiency (B09 EN)、Fructose Metabolism (B11 EN)、Overnight Fasting Blood Glucose Maintenance: Glycogenolysis and Gluconeogenesis (B02 IMG 简化版)。
   - **外部授权参考**：已授权且实际获取的完整 Boards and Beyond (BnB) 与 Dirty Medicine 对应参考课稿全量提供，作为医学脉络与板书抓手参考。
3. **负例隔离规则**：用户明确否决的历史版本（如 B03 旧稿）在对照库中强制标记为 `status: rejected_pending_rewrite`，仅作为问题特征待纠正稿，严禁作为正面教学风格参考。
4. **私密性红线**：公开 skill 规则中绝不打包私有参考声音频、私人全稿正文、项目绝对文件路径及具体文件哈希。项目在私有运行时维护对照清单（记录 `course_id`、`language`、`version`、`user_approval_evidence`、`full_text_hash` 与 `full_text_provided: true`），执行前由工程核验已登记全文均真实加载。

---

## 2. 讲稿教学组织与自拟题处理规范

1. **教学组织与范围拆分优先**：起草全文前，必须先规划教学推进架构与认知阶梯，严禁机械锁定 14 页或死板依照教科书章节编排顺序。
2. **递进式教学推进路径**：`课堂提问/真实困境 → 催化或转化缺了哪一步 → 为什么卡住 → 对应示意图上的生化动作 → 立即用学生自己的话复述/迁移应用`。
3. **自然语感与科学内核并重**：
   - 中文讲稿允许使用自然幽默、中国本土化语境与恰当的生活/临床类比；所拒绝的是无助理解的市井低俗梗、硬造谐音梗以及照本宣科的教材公文腔。不能把词语黑名单、强制每句极短或固定页数当通俗。
   - 先教动作再术语，真正前提必须铺好但不重复全套电子传递链等宏观课；不因白话删减 NADH/NAD+、ATP/ADP、Pi、G6P 或 LDH 等必需辅因子与关键酶分工。
   - 坚决杜绝书面元话、反复施压与无推进重复；长句必须符合中文口语自然停连，一口气读下来不能绕口别扭。
   - 核心图解抓住拓扑与动作即可，无需为了所谓“记忆法”强行编织生硬押韵的口诀。
   - 英文讲稿严格以已获认可的 B02 IMG 简化版难度为准，保持清晰短句与扎实因果。
4. **试题保护与自拟题优化边界**：
   - **真实考试真题/用户提供原题**：题干文字、临床数值与选项严格逐字冻结，不作改动。
   - **项目自拟教学病例（如 B03 当前两道练习题）**：新讲稿允许在保证适龄性与教学顺畅的前提下优化病例生活叙事与表述；但必须严格保留设问的教学目标、选项的科学鉴别含义、第一例化验指标数值以及既定的唯一正确答案，严禁改动后造成多解或答案漂移。

---

## 3. 独立会话初学者因果复述审核协议

新建独立 Gemini 会话执行复述审核，不与写稿或主控会话混用上下文：

1. **角色定义与双重视角**：普通医学本科生 / USMLE 初学者（英文任务为 IMG 初学者）。具备基础生物学常识，但未掌握本课高级机制。审稿人在段落分析前**先连读完整口播文本**，将“局部机制可懂性”与“全文叙事连贯度”分开审视（参见 [narrative-flow.md](narrative-flow.md)）：既查单步因果是否交代完整，也查开头动机是否自然、主转场是否生硬报幕。
2. **顺向认知与禁前置借调**：评估任一教学语义段时，仅允许调动该段文字及此前已讲过的铺垫内容。严禁以后文即将解释的内容替前文脱罪；严禁引入稿外专家背景；严禁伪称进行了真实学生人群试验。绝不能用“引用科学术语复述得出”代替授课自然度。
3. **逐段输出字段要求**：
   - `chunk_id` 与 `original_quote`：原稿位置及精确原文。
   - `novice_paraphrase`：仅凭当前段及此前已讲的口播复述机制动作；若产生困惑，须直说一句真实困惑，而非套用专有名词掩盖。
   - `causal_chain`：提炼本段学到的具体因果链条。
   - `cognitive_obstacles`：检查一口气句子是否绕、书面元话/反复施压/无推进重复，指出跳步、术语未释、定义悬空或生硬教材腔的具体字句；若本段顺畅且交代清楚，如实填写“无”（严禁为了交差强行找错）。
   - `chunk_goal_understood`：本段的局部教学目标是否清晰理解，能否顺畅顺向推演（开篇全局问题在前半节课机制铺垫期尚未完全解决属于正常教学节奏，不自动判定为失败）。
   - `context_check`：必填上下文依赖审核门禁对象，详见 [context-continuity.md](context-continuity.md)。包含固定字段 `checked: true`、`dependencies: []`、`no_dependencies_reason`。仅记录真实依赖；存在依赖时每项必填 `fact`、`use_quote`、`status`（`established_before` | `introduced_here` | `missing` | `unclear`）、`source_chunk_id`、`source_quote`、`learner_question`。无依赖时数组为空且给出非空理由。
4. **医学事实独立解耦**：初学者角色仅评估逻辑闭环与认知负荷，不作为医学事实的终极裁判；事实准确性由独立核查流程负责。

---

## 4. 全库逐段教学功能对照协议

对当前讲稿的每一个教学语义段，在同语种已获认可的全量基准课中寻找承担相同教学功能的段落（引入动机、动作解释、跨段转场、横向对比、题解剖析、总结复盘）进行逐段横向对照：

1. **七维横向对比维度**：口语自然度、必要术语支持、一步一因果、功能性重复（是否有新认知增量）、转场平稳度、图文动作指向、解题工具可用性。
2. **客观可比性与非对称原则**：疾病主题不同，不强求医学事实对称、不强求固定页数、不机械对齐字数与时长；若某份基准课无对应教学功能段，如实记录“该基准课无对应教学功能段，可比性受限”，严禁撰写空洞泛化评价。
3. **全覆盖可核验**：对照报告必须摘录当前段原话与各基准课的具体短原话证据，任何未做比对的段落均视为验收未完成。

---

## 5. 闭环整改与放行标准

1. **全篇上下文整改**：审核中发现的有证据教学缺口，送回 agy 结合全篇上下文修改受影响范围并复验邻段。
2. **交付放行硬性条件**：
   - [ ] 讲稿输出完整性通过工程独立校验（解析最终 response JSON，Schema 校验放行，比对 structured_output 记录版本 hash 与来源，无缺失或冲突，详见 [author-output-integrity.md](author-output-integrity.md)）。
   - [ ] 所有语义段均完成初学者复述，无逻辑悬空。
   - [ ] 逐段 `context_check` 全部通过工程门禁与语义审核，无未铺垫的病例线索、术语或指代脱节（详见 [context-continuity.md](context-continuity.md)）。
   - [ ] 学习闭环核验（learning closure check）通过：基于提前冻结的教学问题清单，逐题通过因果闭环审核，无悬空缺口（verdict 为 pass 且 required_edits 为空，详见 [learning-closure.md](learning-closure.md)）。
   - [ ] 完成与登记清单内同语种全部已获认可课程的逐段功能对照，证据确凿。
   - [ ] 独立医学事实核查通过。
   - [ ] **用户审稿把关点**：用户明确要求“先审稿”时，双重验收通过后**立即停止并呈交中英文完整稿件给用户**，严禁擅自提前启动 MOSS 配音合成、ASR 对齐、分镜生图或视频渲染。
   - [ ] 用户否决高于旧 PASS：凡用户明确否决的历史稿件，绝对不得以旧模型曾给出的 PASS 意见翻案；最终以用户明确验收为准。

## 6. 工程覆盖核验接口与校验契约 (Engineering Verification Contract)

讲稿初学者复述与全库基准对照的输出文件必须严格遵守 learner-review/1 与 selected_refs/1 数据契约，由统一工程脚本进行无偏解析与模式校验。生产发布（release）流程仅能直接消费真实的生产运行凭证与独立来源审计报告，严禁在本地手动伪造或随手合成 PASS 状态。

### 6.1 通用命令行接口 (CLI)

质检执行器采用标准通用参数调用，不携带任何私有凭证或环境硬编码路径：

```bash
python scripts/check_learner_review.py --draft draft.json --language zh-CN --corpus accepted-corpus.json --novice novice.json --comparison comparison.json --out review-check.json
```

- --draft: 待检讲稿 JSON，按语言结构化存储各章节与段落。
- --language: 检查目标语言（zh-CN 或 en-US）。
- --corpus: 动态基准对照库，包含所有经用户明确认可的同语种已获认可课稿。
- --novice: 初学者复述与依赖审核的原始结果 JSON。
- --comparison: 全库基准课程逐段功能比对的原始结果 JSON。
- --out: 输出的工程质检核验汇总凭证。

### 6.2 learner-review/1 契约规范与 Root Verdict 规则

novice.json 与 comparison.json 均必须实现 learner-review/1 根契约标准：
- contract_version: 常量字符串 'learner-review/1'。
- language: 枚举值 'zh-CN' | 'en-US'。
- draft_language_sha256: 64 位十六进制 SHA-256 哈希，精确对应当前待检讲稿语言对象的标准序列化（sort_keys=True, separators=(',', ':')）。
- records: 校验记录数组，不能为空（minItems: 1）。
- required_edits: 阻断性修改要求数组（字符串列表）。
- optional_notes: 非阻断性教学修辞优化建议数组（字符串列表）。
- verdict: 根裁决状态，严格限定为四元枚举：'pass' | 'revise' | 'uncertain' | 'error'。

**Required 与 Optional 严格一致性法则**：
- 只要 required_edits 数组非空（包含至少一条修改项），verdict 绝对禁止标记为 'pass'（必须判定为 'revise' 或 'error'）。
- 唯有在 required_edits 为严格空数组 []，且所有段落记录均达成合规标准时，verdict 方可为 'pass'。
- optional_notes 用于沉淀细微用词、语速偏好或非关键修辞建议，其内容不阻断 'pass' 放行。

### 6.3 初学者复述报告字段规范 (novice.records[]) 与 selected_refs/1

每个教学语义段记录必须包含以下完整字段：
1. chunk_id 与 original_quote: 目标段唯一标识及逐字原稿引文。
2. novice_paraphrase: 初学者白话机制转述（谁对谁做什么、下一步因何发生）。
3. causal_chain: 提取的严密动词因果链条（字符串数组）。
4. cognitive_obstacles: 识别出的绕口句式、教材公文腔、无推进重复、或暴露教案结构的生硬转场（数组）。
5. chunk_goal_understood: 布尔值，当前段教学目标是否被顺畅理解。
6. naturalness_check（口语自然度门禁）：
   固定对象结构：{'spoken_aloud_problem': string, 'ordinary_word_difficulty': string}。
   > [!IMPORTANT]
   > **非空即阻断规则**：此处的字符串设计为阻断性缺陷指示器。任一字段非空都会触发机械拒放。必须先区分模型报告格式错误与有证据的真实内容缺陷；例如误填“无问题”属于响应格式错误，不得据此判口播有缺陷或改讲稿。若段落开头或转场存在严重影响听课体验的生硬割裂、且有确切相邻原话证据，写入 `spoken_aloud_problem` 并附带确切修改进 `required_edits`；若仅为可选措辞风格建议，必须放入 `optional_notes`，严禁填入阻断字段。若本段朗读顺畅、无生僻词理解障碍，**必须填为空字符串 ''**。严禁填写 '无问题'、'无' 或任何说明文字。
7. context_check（上下文依赖门禁）：
   固定对象结构：{'checked': true, 'dependencies': [...], 'no_dependencies_reason': string | null}。
   - dependencies 记录当前段向前引用的前提事实。
   - **合法新引入放行法则**：对于首度交代的新概念、公理或破题导言，无前置依赖时不得虚构依赖，dependencies 设为空数组 []，并在 no_dependencies_reason 中如实填写合理解释（例如：'本句为本课核心目标陈述，属首次公开定义，无前置事实依赖'）；存在依赖时 no_dependencies_reason 必须为 null。
   - 依赖项字段：fact, use_quote, status, source_chunk_id, source_quote, learner_question。
   - **状态规则**：
     * introduced_here：在当前段中首次明确引入或定义。允许定义本身与引用发生于同句，其 source_quote 可包含或严格先于 use_quote 出现，不与后文交叉重叠。
     * derived_here：基于已有事实在当前句通过严密因果逻辑推导得出，证据使用 source_chunk_id 与 source_quote；前缀引用选择接口另用 source_refs。
     * established_before：前文已确立。必须附带合法的先前 source_chunk_id 与精确 source_quote。
     * missing / unclear：属于硬缺口，必须附带具体的初学者卡点提问 learner_question；凡依赖关系已解决者，learner_question 必须为 null。
8. **selected_refs/1 前缀探针 typed claims 规约**：
   在前缀审核协议中，复述断言采用 typed teach_back_claims 结构化呈现，每条 claim 必须指定属性：patient_observation、general_mechanism、inference、missing_information。每条 claim 选取的 source_refs 必须作为整体完全支撑该主张的所有因果要素。

### 6.4 独立来源审计报告规范 (source_audit)

实际机器接口以 `scripts/check_source_adjudication.py` 的 `ROW_SCHEMA` 为准，使用 `source-adjudication/1` JSONL；每行包含 `case_id`、`item_id`、`disposition`、`reviewer`、`bindings`、`rationale`、`scope_check`、`citations`、`counterevidence`、`correction`、`checkpoint_context`。它逐项核验当前检查点、claim、dependency、required edit 与负控；来源证据为精确 ID、段落、字符范围与文本哈希。原始台账与校验结果分别保存，不能只填 audited 标记。公开说明不代替实际 Schema；校准专用范围 `calibration_control` 不得用作生产来源审核凭据。

### 6.5 全库功能对照报告字段规范 (comparison.records[])

对比报告驱动讲稿与全库已认可基准课（accepted-corpus.json）展开同语种横向对照：
- chunk_id 与 original_quote: 当前段信息。
- paragraph_acceptable: 布尔值，本段在横向对比下是否达到同等教学质量标准。
- comparisons: 数组，覆盖动态登记的同语种全部前课：
  * reference_key: 基准课程唯一标识。
  * comparable: 布尔值，该基准课是否存在同等教学功能段。
  * reference_block_id / reference_quote / limitation: 真实前课引句、块 ID 与可比性限制，按当前消费者校验。
  * observation: 对比观察分析（必填非空，严禁空泛背书）。
  * required_change: 针对本段的具体改写要求（无改动时填空字符串 ''）。

### 6.6 产物身份、工具哈希与生产消费

- **哈希多维绑定**：质检报告必须同时锁定并核验 checker_sha256（校验脚本哈希）与 schema_sha256（数据模式哈希）。任何脚本或 Schema 变更均使旧凭证失效，严禁使用新 wrapper 包装旧结果伪造通过。
- **放行边界**：工程校验通过仅生成 text_gate_ready: true，绝对不等于用户已验收（user_accepted）。任何讲稿字面修改均导致 draft_language_sha256 失效，必须重走对应 DAG 节点重新计算状态。

### 6.7 学习闭环核验接口与校验契约 (scripts/check_learning_closure.py)

讲稿初学者因果闭环审核由统一工程脚本进行覆盖与一致性核验：

```bash
python scripts/check_learning_closure.py --draft draft.json --language zh-CN --plan plan.json --review closure.json --out closure-check.json
```

- **数据契约规范**：以相邻 `scripts/learning_closure.schema.json` 为实际字段与枚举定义。`learning-closure-plan/1` 采用 `contract_version`、`language`、`goals`（`id`、`question`、`kind`、`introduced_at`、`resolution_by`、`importance_reason`）与 `paired_units`；`learning-closure-review/1` 采用 `answers`（`goal_id`、`status`、`answer`、`source_refs`、`missing_link`、`reason`），引用键为 `paragraph_id` 与 `quote`。
- **校验原则**：代码仅核验版本一致性、引文覆盖与无未决阻断项，因果语义蕴含仍须逐项独立核实；`closure-check.json` 直接作为 script-review 中 learner 检查的组成凭证。

