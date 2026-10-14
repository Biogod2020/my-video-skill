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
   - **当前登记基准课**（中英各 3 份，动态追加）：
     - 中文正例：G6PD缺乏症（B09）、果糖代谢障碍（B11）、夜间禁食血糖维持：糖原分解与糖异生（B02 中文版）。
     - 英文正例：G6PD Deficiency (B09 EN)、Fructose Metabolism (B11 EN)、Overnight Fasting Blood Glucose Maintenance: Glycogenolysis and Gluconeogenesis (B02 IMG 简化版)。
   - **外部授权参考**：已授权且实际获取的完整 Boards and Beyond (BnB) 与 Dirty Medicine 对应参考课稿全量提供，作为医学脉络与板书抓手参考。
3. **负例隔离规则**：用户明确否决的历史版本（如 B03 旧稿）在对照库中强制标记为 `status: rejected_pending_rewrite`，仅作为问题特征待纠正稿，严禁作为正面教学风格参考。
4. **私密性红线**：公开 skill 规则中绝不打包私有参考声音频、私人全稿正文、项目绝对文件路径及具体文件哈希。项目在私有运行时维护对照清单（记录 `course_id`、`language`、`version`、`user_approval_evidence`、`full_text_hash` 与 `full_text_provided: true`），执行前由工程核验已登记全文均真实加载。

---

## 2. 讲稿教学组织与自拟题处理规范

1. **教学组织与范围拆分优先**：起草全文前，必须先规划教学推进架构与认知阶梯，严禁机械锁定 14 页或死板依照教科书章节编排顺序。
2. **递进式教学推进路径**：`课堂提问/真实困境 → 催化或转化缺了哪一步 → 为什么卡住 → 对应示意图上的生化动作 → 立即用学生自己的话复述/迁移应用`。
3. **自然语感与科学内核并重**：
   - 中文讲稿允许使用自然幽默、中国本土化语境与恰当的生活/临床类比；所拒绝的是无助理解的市井低俗梗、硬造谐音梗以及照本宣科的教材公文腔。
   - 严禁为了“求通俗”而删减关键科学机制、必需辅因子（如 NADH/NAD+、ATP/ADP、Pi）或关键酶（如 LDH）的代谢分工；讲清通俗机制后，必须精准对应科学术语。
   - 核心图解抓住拓扑与动作即可，无需为了所谓“记忆法”强行编织生硬押韵的口诀。
   - 英文讲稿严格以已获认可的 B02 IMG 简化版难度为准，保持清晰短句与扎实因果。
4. **试题保护与自拟题优化边界**：
   - **真实考试真题/用户提供原题**：题干文字、临床数值与选项严格逐字冻结，不作改动。
   - **项目自拟教学病例（如 B03 当前两道练习题）**：新讲稿允许在保证适龄性与教学顺畅的前提下优化病例生活叙事与表述；但必须严格保留设问的教学目标、选项的科学鉴别含义、第一例化验指标数值以及既定的唯一正确答案，严禁改动后造成多解或答案漂移。

---

## 3. 独立会话初学者因果复述审核协议

新建独立 Gemini 会话执行复述审核，不与写稿或主控会话混用上下文：

1. **角色定义**：普通医学本科生 / USMLE 初学者（英文任务为 IMG 初学者）。具备基础生物学常识，但未掌握本课高级机制，对未铺垫的跳跃和教材腔极为敏感。
2. **顺向认知与禁前置借调**：评估任一教学语义段时，仅允许调动该段文字及此前已讲过的铺垫内容。严禁以后文即将解释的内容替前文脱罪；严禁引入稿外专家背景；严禁伪称进行了真实学生人群试验。
3. **逐段输出字段要求**：
   - `chunk_id` 与 `original_quote`：原稿位置及精确原文。
   - `novice_paraphrase`：仅凭本段与已学前置，用初学者自己的话复述机制动作。
   - `causal_chain`：提炼本段学到的具体因果链条。
   - `cognitive_obstacles`：指出跳步、术语未释、定义悬空、生硬教材腔或冗余堆叠的具体字句；若本段顺畅且交代清楚，如实填写“无”（严禁为了交差强行找错）。
   - `chunk_goal_understood`：本段的局部教学目标是否清晰理解，能否顺畅顺向推演（开篇全局问题在前半节课机制铺垫期尚未完全解决属于正常教学节奏，不自动判定为失败）。
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
   - [ ] 所有语义段均完成初学者复述，无逻辑悬空。
   - [ ] 完成与登记清单内同语种全部已获认可课程的逐段功能对照，证据确凿。
   - [ ] 独立医学事实核查通过。
   - [ ] **用户审稿把关点**：用户明确要求“先审稿”时，双重验收通过后**立即停止并呈交中英文完整稿件给用户**，严禁擅自提前启动 MOSS 配音合成、ASR 对齐、分镜生图或视频渲染。
   - [ ] 模型意见仅为审查参考，最终以用户明确验收为准；历史被否决稿件不因模型评分而翻案。

## 6. 工程覆盖核验接口

```bash
python scripts/check_learner_review.py \
  --draft draft.json --language zh-CN \
  --corpus accepted-corpus.json \
  --novice novice.json --comparison comparison.json \
  --out review-check.json
```

```text
draft.languages[language].sections[].paragraphs[]:
  id, spoken_text
corpus[]:
  key, language, status=COMPLETE, reference_role=accepted_course_prose,
  acceptance_basis, full_script_sha256, blocks[{id,text}]
novice / comparison:
  language, draft_language_sha256, records[], required_edits[]
novice.records[]:
  chunk_id, original_quote, novice_paraphrase, causal_chain[],
  cognitive_obstacles[], chunk_goal_understood, prerequisites[{chunk_id,quote}]
comparison.records[]:
  chunk_id, original_quote, paragraph_acceptable, comparisons[]
comparison.records[].comparisons[]:
  reference_key, comparable, reference_block_id, reference_quote,
  limitation, observation, required_change
```

`draft_language_sha256` = SHA256(UTF-8(JSON(language_object, sort_keys=True, ensure_ascii=False, separators=(",", ":")))).
`full_script_sha256` = SHA256(UTF-8("\n\n".join(block.text))).
`text_gate_ready` ≠ `user_accepted`；医学事实核查独立记录。
