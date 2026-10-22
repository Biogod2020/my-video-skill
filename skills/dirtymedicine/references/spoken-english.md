# 英文医学口播讲稿规范（IMG 简化版基准）

本规范以 B02 英文课程（IMG 简化版）为基准，规定后续所有英文医学课程的语言难度、句式结构与多模态对齐标准。

## 1. 语言难度与表达定位
- **普通语言基准**：后续所有英文课程以面向国际医学生（IMG）的通俗课堂英语为基准，对齐 B1-B2 的日常理解深度。此定位仅作为平实通俗的写作方向，不声称通过任何官方 CEFR 测评。
- **拒绝修辞干扰**：严禁文学腔、商业公文腔、冷僻普通词、难懂社会文化梗与汉译英直译。用日常口语动词替代生涩用词（如用 liver 替代习惯性 hepatic，用 decrease/drop 替代 dwindle/drawdown，用 work together 替代 in tandem）。
- **前后改写示例**：
  - *Before (文学/生涩)*: "Gluconeogenesis orchestrates de novo glucose synthesis to buffer the drawdown of glycogen reserves."
  - *After (通俗/因果)*: "Gluconeogenesis makes brand new glucose from raw materials in the blood as liver glycogen stores decrease."
  - *Before (直译口诀)*: "Staying up late harms the liver."
  - *After (场景因果)*: "To remember this easily, think about an overnight fast where someone goes about twelve hours without food. As liver glycogen stores drop, gluconeogenesis must step in and provide a larger share of glucose."

## 2. 句式结构与教学因果
- **动作与因果推进**：优先采用常用口语动词、短而完整的单句，一步交代一个生化反应或临床动作。保证主谓指代清晰、前后因果明确。段际衔接与开篇叙事逻辑对齐共享规范 [narrative-flow.md](narrative-flow.md)，避免机械的提纲报幕词（如频繁使用 "Next, let us..."）。
- **教学深度不妥协**：严禁为了追求“简短”而删减核心机制推导或降低 USMLE 知识深度。允许自然完整的复合从句，不硬性设置每句单词上限；严禁为了缩短而切碎句子、机械堆叠设问、或在每个逗号处机械插入停顿。

## 3. 医学专名与试题保护
- **原题原样保留**：考试题干、选项文字、临床数值及实验条件严格逐字保留，不得因“语言简化”改写考题原本表述。
- **专名功能解释**：必须保留的核心医学术语首次出现时紧跟一句简短直白的功能解释（如 hepatocytes 解释为 liver cells，diaphoresis 解释为 excessive sweating，palpitations 解释为 pounding heartbeat）。后续自然使用专名，不机械重复双语全称，亦不强制要求每个生化酶名降至初级词汇。
- **病例时间与数字口语规范化**：严格区分**时刻（clock time）**与**历时（duration）**。在自拟病例与讲解场景中，避免生硬的军用/24 小时制口播（如不说 `eighteen hundred`，而改用通俗直观的 `six p.m. the previous evening`；次日时刻使用 `noon the next day` 等），确保面向 IMG 的自然直观性；屏幕显示可使用 `18:00 (6 p.m.)` 兼顾严谨。真实原题的题干与选项数值必须逐字严格保留，不得擅自修改原题原数字；口语层的自然化转换必须保持医学数值等价并在映射表中全程追踪。数字读法连同医学术语与单位在 preflight 阶段送模型专门审核，严禁以 TTS 发音听审 PASS 代替对口语表达直观度的验收。

## 4. 协同输入与审查闭环
- **Agy 参考输入**：调用 agy 撰写或译写英文讲稿时，私有 prompt 必须附带已获认可的完整 B02 简化课稿（仅限私有任务输入，严禁公开打包散发）作为难度参照，并结合完整既有参考课与当前上下文联合提示。本轮 B02 英文底模配音（MOSS-TTS-v1.5 8B base，13:54）已获用户发声认可，后续英文课程在此基础上固定工作流（见 [moss-native-baseline.md](moss-native-baseline.md)），并按需安排稀疏留白派生与病例时间口语优化。
- **Gemini 文稿与听审审查**：独立会话审查文稿时，对发现的难懂普通词和冗长句列出具体实例及推荐的通俗替代句，未发现时如实记录；多模态听审时，须明确确认初学者的听觉负荷能否从容跟上当前解释节奏。
- **多模态时序核查**：讲稿简化后，必须重新核验口播台词、短字幕断句、visual cue 触发点与图解高亮、原题数据及选项画面的时序映射，确保音画步调一致。
