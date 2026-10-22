# 课程质检门禁与凭据重算规范 (Quality Gates Specification)

本规范定义医学教学讲稿、配音与成片全流程的统一质量门禁标准与消费法则。所有质检状态必须由 scripts/course_qc.py 严格依据 course-qc-policy/1 策略配置从底层原始证据重新计算，严禁形式主义盖章与状态盲目继承。

## 1. 统一质检执行器与凭据重算原则

1. **原始凭据强力重算**：
   - scripts/course_qc.py 是质检状态计算的唯一官方入口，必须直接读取底层生成的原始证据文件（proofs/artifacts）并校验内容寻址哈希（SHA-256）。
   - 严禁轻信任何中间状态、缓存的 ready 标记或孤立的局部 PASS 判定。
   - 明确状态语义界限：REVIEW_READY 仅表示送审材料与前置工程流水线已就绪，绝对不代表用户接受（user_accepted），更不代表已获准发布（published）。
2. **三级目标路由（Targets）与 Policy 绑定**：
   质检目标必须严格按照 Policy JSON 实际配置动态装配检查项，严禁执行器私自发明或硬编码：
   - script-review（文稿阶段）：必须全量通过 author, medical, learner, comparison, prefix, calibration, source_audit 共 7 项检查。其中 learner 门禁必须消费当前讲稿与问题计划对应的闭环核验凭证（scripts/check_learning_closure.py 输出的 closure-check.json，详见 [learner-review.md](learner-review.md) 与 [learning-closure.md](learning-closure.md)），无需新设独立 release 层级；文稿阶段全通仅送用户审稿，严禁擅自启动配音与视频渲染。
   - private-video-review（成片内审阶段）：在文稿阶段基础上，增加 voice_recipe, audio_engineering, audio_review, captions, visual_engineering, video_engineering, video_review，完成工程指标与多模态双重闭环。
   - publish（正式发布阶段）：在成片内审基础上补充 publication_metadata 检查（涵盖课程编号、品牌视觉、双语分发元数据）。
3. **状态机定义与唯一放行标准**：
   - 检查状态全量枚举：NOT_RUN, RUNNING, PASS, FAIL, UNCERTAIN, ERROR, STALE。
   - **唯一放行状态**：仅有 PASS 状态具备放行资格。UNCERTAIN、FAIL 或 ERROR 均构成绝对阻断。
   - **失效与重新绑定禁令**：当讲稿、音频、分镜或提示词版本发生变更时，受影响检查项立即置为 STALE。旧版本的原始回执与证明文件严禁‘换壳’绑定到新哈希产物上，必须全量触发复验。inner 结果的 tool/schema hash 必须与当前脚本及 Schema 精确匹配，禁止用新 wrapper 套用旧 PASS 产物。

## 2. 独立来源审计 (source_audit) 与专用工程验证工具链

1. **独立来源审计关卡 (source_audit)**：
   - **角色定位**：Gemini/agy 的前缀审查输出仅作为候选报告，绝对不把同模型多数票当证明。必须由独立于讲稿作者的证据核验者（可由 Codex 子代理执行，但严禁假称真实学生人群）实际逐项比对当前 prefix 正文与原始审查报告，裁决来源真伪。
   - **全量 Checkpoint 穿透核验**：针对每个检查点，必须核验 checkpoint_context（主动核查首依赖，不局限于模型已列清单）、每一条 claim_id、依赖项索引、required_edit 索引及负控拒答。
   - **四元裁决枚举与证据要求**：
     * SUPPORTED：前文或当段引据真实、完整支持该主张。
     * REVIEWER_ERROR：模型审查器幻觉误报（如将通用机理误当患者数据或虚构前置依赖）。必须依此纠正审稿器，绝对禁止据此错误修改原本正确的讲稿。
     * COURSE_GAP：确凿的讲稿逻辑或信息断层。明确阻断后交回 agy 进行局部精准整合改稿。
     * UNCERTAIN：证据含混或无法确证。
     * 有实际来源时附精确 source ID、段落和字符范围；缺失信息与负控可无来源并说明依据，严禁伪造引据。每项仍须核验主体、条件和程度。
   - **放行硬门禁**：必须满足 independent_audit_completed: true、all_items_audited: true 且 unresolved: []。任何漏项、未决存疑（UNCERTAIN）或未闭环的 COURSE_GAP 坚决不予放行。
   - **机械 Consumer 校验**：自动化消费者必须强校验输入文本覆盖度、当前 input、ref_index、raw_result、protocol、formatter 及 decoder 的哈希一致性，确认独立裁决具备原始记录、检验结果与 session 身份，严禁仅自填 audited: true 虚假应付。
2. **讲稿与发音生成链校验 (scripts/check_course_author_chain.py)**：
   - 强制从模型最终单一 response JSON、对应 Schema 与修改前 baseline 重新重构有界 patch 及 TTS 发音输入，不只凭上游声明的 application passed 放行。
3. **配音工程配方审计 (scripts/audit_voice_recipe.py)**：
   - 核验实际配音 profile 哈希、加载的 LoRA 权重、底模、codec 及 TTS 来源合规性。
4. **音频工程一致性核查 (scripts/check_narration_engineering.py)**：
   - 严格核验 24kHz 单声道、原生 EOS 单 block 生成、无预设时长目标、无全局 tempo 机械拉伸与无逐段重启的波形拼接；ASR 识别差异与语速异常仅作为候选复听线索，禁止机械重定时。
5. **语义字幕逆映射与像素级核验 (scripts/build_semantic_captions.py)**：
   - 维护有序 display_segments 映射（spoken == 实际TTS发音、display == 原稿字面），保护缩写与全名；脚本执行逐字/词时轴覆盖、语义断句、标点和帧时长规则校验，严禁模型估算词秒。它不接收视频；实际视频帧须另行抽取、核验并归档，builder PASS 不能代替真实帧验收。
6. **全量媒体实体验收与同归档**：
   - 输送给模型审核的媒体哈希（input_media_sha256）必须与工程导出的完整媒体哈希（audio_sha256 / video_sha256）严格一致并同报告记录，严禁用摘要或短片代替完整媒体。

## 3. 校准定位转向 (scope=limited_assisted_use) 与盲测教训

1. **放弃单次调参完美的执念**：
   - 明确放弃通过无限微调提示词追求 Gemini 单次前缀审查完美。v3 最新盲测证实，模型仍会将通用病种表现误当当前病例线索，并给出错误的 required edits，证明 4/4 主标签命中不足以代表审查可信。
2. **真实保留失败记录与有限辅助定位**：
   - 既有已阻断的测试样例与 holdout_passed: false 记录全量真实保留，严禁篡改历史分数，严禁将已曝光测试样反复包装为‘未见 Holdout’刷取 PASS。
   - calibration 检查范围明确设定为 scope = 'limited_assisted_use'，其职责仅为：验证已知历史失败已被如实记录、独立来源审计是必需的补充、且独立控制机制能够准确检出历史失败案例。
   - 探针报告中的模型原始 Holdout 正确率与错误清单必须原样列示；Control 验证通过仅代表‘辅助审核协议可用’，绝不证明单模型绝对可靠，更不代表课程本身通过。
   - 生产放行必须额外消费当前课程真实的逐项来源审计（source_audit）与完整音视频实审结果。
3. **负控超纲拒答法则**：
   - 阴性对照（Negative Control）任务用于检验模型是否严格依托材料判定。超出材料范围时，探针必须如实判定 answerable_from_material: false，答案置 null。
   - 严禁底座大模型利用未公开的医学专家先验常识擅自‘帮材料补课’。擅自答对材料未包含的内容属于‘探针保真度崩溃’，该次质检自动作废。

冻结的通用前缀模型协议见 [qc-reviewer-protocol.md](qc-reviewer-protocol.md)。实际调用须按此协议和当前精确前缀生成提示词，不把私有课程例子或预期标签写入通用协议。

## 4. 全文自然度审核与物理前缀审核的分工边界

1. **双重角色明确解耦**：
   - **全文自然度审核 (full_learner_protocol)**：审查者允许查阅讲稿全文，评估整体教学脉络、口语自然度和听觉节奏感，但严禁声称自身具备物理前缀隔离能力。
   - **物理前缀审核 (reviewer_protocol)**：审查者严格受限于当前断点之前的物理前缀输入，专注首依赖穿透、潜在逻辑断层风险探测（risk probes）与全课逐段覆盖。必须配备显式 risk inventory，且至少包含一个负控用例。
   - 两项检查独立绑定各自策略与 Schema，严禁将历史全文审核记录伪称为已通过 v3 前缀探针审查。
2. **模型 IO 与重试底线**：
   - 模型调用仅允许在遭遇网络传输失败（transport error）或输出格式严重违背 Schema 时，执行有限次数的同请求重试。
   - 当模型返回有效的语义审查修改意见（verdict: revise）时，**绝对禁止通过重新抽样重试来‘刷出 PASS’**。
   - 格式问题先修复模型输出格式，或按同一冻结请求有限重试；仅在证实消费者有缺陷时修复消费者并重跑，不得削弱合同以迎合错误输出；真实内容问题必须交回 agy 进行最小范围精准改稿，随后重跑受影响的 DAG 节点及成对问答单元（paired_units）和受影响邻段联动复验，严禁仅改单句而遗留跨段因果脱节，严禁为了迁就审核器缺陷而误改优质讲稿。
   - 非核心措辞偏好统一归入 optional_notes，宽容对待，不强求每个学科公理都在开场重复定义或机械塞满。
