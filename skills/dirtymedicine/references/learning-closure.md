# 教学闭环与核心因果检验规范 (Learning Closure Specification)

本规范定义医学讲稿在写作与改稿全流程中的教学因果闭环标准。旨在确保初学者不仅能复述孤立事实，更能仅凭课内给出的机制动作完整推导出临床表型，消除直觉反常困惑，杜绝讲稿出现悬空断层。

---

## 1. 教学问题清单与闭环原则 (Problem Inventory & Closure)

1. **写前/改前冻结问题清单**：
   - 在新写或修订讲稿前，必须首先显式冻结一份学习目标核心问题清单（契约 `learning-closure-plan/1`），明确本课学生听完后必须能独立回答的核心疑问。
   - 问题种类包括：机制（`mechanism`）、核心临床表现（`clinical_manifestation`）、保留功能反问（`preserved_function`）、迁移应用（`application`）以及负控超纲问题（`out_of_scope`）。
   - 不锁定固定问题数量，依据课程核心教学目标设定，避免形式主义充数。
2. **三步因果闭环链条**：
   - 从核心症状出发追问，再按 `缺陷或条件变化 → 具体生化/生理动作 → 临床后果` 解释完整因果链。
   - 严禁停留在“由于该酶缺陷所以导致某症状”的标签化跳步；必须点明：缺陷导致哪步分子反应受阻、底物或产物发生何种具体走向改变、此改变如何对细胞或器官造成直接生理后果。
3. **保留功能反问机制 (Intact Pathway Paradox)**：
   - 当讲稿强调某条代偿通路完好或部分功能保留时，若该保留功能在直觉上容易引发反问（如“既然糖异生完好，为何还会低血糖或脏器肿大？”），讲稿必须主动解答该反常困惑。
   - 必须交代消除矛盾的关键动作机制（例如限速底物供应是否受限、异常结构是否物理占据空间等），打消初学者疑虑。
4. **合理教学边界与不强求项**：
   - **不要求单句闭环**：允许因果链条在相邻语义段中递进展开，但核心机制必须在实际用于推导结论之前铺垫完毕。
   - **不强求疾病百科**：与核心教学主线无关的次要并发症或偶然病例细节不纳入强制闭环。
   - **不强求未经证实的定量模型**：不强推绝对通量分配比、固定代谢百分比或未经实证的禁食时间切点，仅解释支撑教学结论所必需的定性因果条件。
   - **对照疾病最小理解**：对照疾病只需讲透与当前主题形成鉴别所必需的机制差异，不强制展开对照疾病的全套病理百科。

---

## 2. 跨段联动与受影响范围 (Cross-Chunk Coupling)

1. **成对问答单元联动 (paired_units)**：
   - 计划中明确标定提问引入段落（`introduced_at`）与最终解答段落（`resolution_by`）。
   - 允许跨段设问与递进作答，但在最终解决之前不得凭空引用未解释的机制假说。
2. **局部改稿联动复验**：
   - 修订任一问题涉及的段落时，必须将对应的成对单元（`paired_units`）与受影响邻段一并纳入复验范围。
   - 严禁孤立修改单句而破坏跨段问答衔接或在前文遗留悬空伏笔。

---

## 3. 独立材料审核与历史回归

1. **绝对依托材料原则（严格 Grounding）**：
   - 审核者仅凭当前送审讲稿文本回答问题，并必须提供逐字原稿引文（`source_refs`）。
   - 严禁审核者调动未在材料中出现的外部专家知识“替讲者补课”。材料未交代因果步骤时，必须如实判定为 `missing` 或 `unclear`，绝不能判定为通过。
2. **真实盲测与历史回归规范**：
   - 新旧稿件对比测试必须在完全独立的会话中进行，向模型输入完全相同的中立学生问题与超纲负控题。
   - 严禁向模型注入版本标签（如“旧稿/修复稿”）、预期判决倾向、另一版本的比对材料或作者改稿意图说明。
   - 针对已知用例的评测如实标注为“历史回归基准”（historical regression），严禁包装为“未见 Holdout 数据”。
   - 真实失败记录必须全量保留，严禁在有效 `revise` 后通过同提示词重抽刷取 `PASS`。
3. **非计划缺口识别 (Unplanned Gaps)**：
   - 复述审核必须允许审查者主动提出原问题清单未覆盖但在推导中暴露的核心疑问（`unplanned_gaps`），不能因清单未列就豁免检查。
   - 明确证明为讲稿逻辑断层的非计划缺口与计划内 `missing` 项同样作为硬性阻断项（`required_edits`），非核心修辞建议列入 `optional_notes`。
4. **杜绝表面达标伪象**：
   - 单纯关键词命中、固定句数限制或多次模型多数票均不能作为理解达标的证据；必须逐项检视因果蕴含真实成立。

---

## 4. 工程校验脚本与数据契约 (Engineering Contract)

质检流程通过统一 CLI 脚本驱动无偏校验，集成于 `script-review` 阶段的 `learner` 门禁中：

```bash
python scripts/check_learning_closure.py --draft draft.json --language zh-CN --plan plan.json --review closure.json --out closure-check.json
```

1. **实际契约**：字段、类型与枚举以 `scripts/learning_closure.schema.json` 为准，不另造同名接口。
   - `plan`：`contract_version`、`language`、`goals`（含稳定 `id`、`question`、`kind`、`introduced_at`、`resolution_by`、`importance_reason`）、`paired_units`。
   - `review`：`contract_version`、`language`、`draft_language_sha256`、`plan_sha256`、`answers`（`goal_id`、`status`、`answer`、`source_refs`、`missing_link`、`reason`）、`unplanned_gaps`、`required_edits`、`optional_notes`、`verdict`。
   - `source_refs` 使用 `paragraph_id` 与原话 `quote`。`missing`/`unclear` 不得填入稿外答案；`out_of_scope` 不补答案、不当作课稿缺陷。
   - `plan_sha256` 与 `draft_language_sha256` 均采用 UTF-8 JSON 的标准序列化哈希（`ensure_ascii=False, sort_keys=True, separators=(',', ':')`）；CLI 另记录计划文件实际字节哈希 `plan_file_sha256` 供放行机制绑定。
2. **放行约束**：计划内核心问题未答、引用不实、清单覆盖不全、未处理的 `unplanned_gaps` 或 `required_edits` 均阻断 learner 门禁；仍须独立核实回答是否真正由引文支持。
3. **代码与语义分工界线**：
   - 代码脚本负责严格核验文件版本哈希一致性、引文在原文中真实存在、计划问题覆盖率及阻断项是否为空。
   - 机器代码不证明因果语义蕴含，文字的科学逻辑闭环由独立模型与来源审计逐项判定。
   - 文稿阶段通过仅表示达成送审标准，送交用户人工审阅，绝对不自动触发配音合成与视频渲染。
