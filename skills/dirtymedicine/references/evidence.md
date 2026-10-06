# 证据溯源、样本档案与纠错记录

本技能基于已完成下载的公开课程视频英文字幕、关键画面采样帧及本地学习资料进行提炼与核查。本文件记录具体研究样本、时间戳证据链，并对原公开课中已查证的科学疏漏给出明确的校正标准。

---

## 1. 研究范围与语料覆盖核算

- **分析基准日期**：2026-10-04。
- **核心通读样本**：12 节公开视频英文字幕，清除滚动重复文本后共计 26,593 个英文空白分词，课程视频总时长 169.9 分钟。
- **画面与关键帧采样**：核对 144 张画面（包含 108 张按时长分布的状态采样帧，以及 36 张抓取关键内容揭示事件的采样帧；采样基于内容推进节点）。
- **本地参考讲义**：查阅本地 `DirtyMedicine.pdf`（署名 ROCKS2018，2020 年汇编，全书 412 页，为第三方学习笔记汇编，非权威官方定稿）中的 14 页核心内容（第 32–33、60–62、163、211–213、323–325、391–392 页）。
- **前期研究沉淀**：此前通读的 8 节镜像全文（28,098 词）已在本地独立归档，清单索引见 `projects/dirtymedicine-study/manifest.json`。
- **语料边界说明**：当时抓取课程清单约为 350 条。自动化脚本提取了 91 份机器转写文件，属于机器粗提，未完整观看全部音视频，不计入通读数量。
- **本地仓库根目录路径**：
  - 资产与哈希清单：`projects/dirtymedicine-study/corpus/video-analysis-20261004/inventory.json`
  - 采样拼图：`projects/dirtymedicine-study/corpus/video-analysis-20261004/sheets/`
  - 单帧目录：`projects/dirtymedicine-study/corpus/video-analysis-20261004/frames/<视频 ID>/`

---

## 2. 12 节核心分析样本与视频时间戳索引

| 课程标题 | 视频 ID | 词数 | 时长 | 关键时间戳链接 | 制作观察与结构特征 |
| :--- | :--- | ---: | ---: | :--- | :--- |
| **Occupational Lung Diseases** | `FqjLNB2TLJ0` | 2891 | 17:32 | [02:06](https://www.youtube.com/watch?v=FqjLNB2TLJ0&t=126s), [04:12](https://www.youtube.com/watch?v=FqjLNB2TLJ0&t=252s), [10:31](https://www.youtube.com/watch?v=FqjLNB2TLJ0&t=631s), [16:50](https://www.youtube.com/watch?v=FqjLNB2TLJ0&t=1010s) | 暴露、发病机理、表现沿相同维度展开；红字集中于鉴别点；引入病理照片承接形态辨识 |
| **Gout vs. Pseudogout vs. Septic Arthritis** | `XImkx3-OlS4` | 1748 | 10:13 | [01:13](https://www.youtube.com/watch?v=XImkx3-OlS4&t=73s), [03:40](https://www.youtube.com/watch?v=XImkx3-OlS4&t=220s), [08:35](https://www.youtube.com/watch?v=XImkx3-OlS4&t=515s) | 开场直接给出完整对比总表，逐病展开机制，最后回图核对鉴别点；确立总览表先行的可行性 |
| **Aphasia** | `HpOaVyhuMW4` | 3093 | 19:44 | [02:22](https://www.youtube.com/watch?v=HpOaVyhuMW4&t=142s), [07:06](https://www.youtube.com/watch?v=HpOaVyhuMW4&t=426s), [09:28](https://www.youtube.com/watch?v=HpOaVyhuMW4&t=568s), [16:34](https://www.youtube.com/watch?v=HpOaVyhuMW4&t=994s), [18:56](https://www.youtube.com/watch?v=HpOaVyhuMW4&t=1136s) | 以复述能力分组；流利性、理解力、复述三项指标位置固定；使用固定位置勾叉标记 |
| **Heavy Metal Toxicity** | `QwJdYIN5iUI` | 7630 | 47:50 | [02:05](https://www.youtube.com/watch?v=QwJdYIN5iUI&t=125s), [14:15](https://www.youtube.com/watch?v=QwJdYIN5iUI&t=855s), [31:25](https://www.youtube.com/watch?v=QwJdYIN5iUI&t=1885s), [34:26](https://www.youtube.com/watch?v=QwJdYIN5iUI&t=2066s), [36:30](https://www.youtube.com/watch?v=QwJdYIN5iUI&t=2190s) | 大量知识点按可识别线索取舍；解毒药与毒物直接关联，不强行编造长故事 |
| **Collagen Synthesis** | `Y32gdtprEj4` | 1398 | 09:19 | [02:35](https://www.youtube.com/watch?v=Y32gdtprEj4&t=155s), [02:55](https://www.youtube.com/watch?v=Y32gdtprEj4&t=175s), [03:10](https://www.youtube.com/watch?v=Y32gdtprEj4&t=190s), [04:15](https://www.youtube.com/watch?v=Y32gdtprEj4&t=255s) | 前几步保留在位，逐步增量补全机制；右侧加入动作标签，保持图位稳定 |
| **Arachidonic Acid Pathway** | `Wz8OwDVvyJ0` | 1812 | 13:59 | [01:40](https://www.youtube.com/watch?v=Wz8OwDVvyJ0&t=100s), [03:21](https://www.youtube.com/watch?v=Wz8OwDVvyJ0&t=201s), [06:25](https://www.youtube.com/watch?v=Wz8OwDVvyJ0&t=385s), [06:50](https://www.youtube.com/watch?v=Wz8OwDVvyJ0&t=410s), [10:25](https://www.youtube.com/watch?v=Wz8OwDVvyJ0&t=625s), [11:10](https://www.youtube.com/watch?v=Wz8OwDVvyJ0&t=670s) | 先建分支拓扑，转到功能表，再回原图覆盖药物作用位点；颜色用于追踪分支与位点 |
| **Insulinoma vs. Factitious Hypoglycemia** | `OxCwFU0LhKI` | 1850 | 12:08 | [01:27](https://www.youtube.com/watch?v=OxCwFU0LhKI&t=87s), [02:54](https://www.youtube.com/watch?v=OxCwFU0LhKI&t=174s), [05:00](https://www.youtube.com/watch?v=OxCwFU0LhKI&t=300s), [05:40](https://www.youtube.com/watch?v=OxCwFU0LhKI&t=340s), [06:20](https://www.youtube.com/watch?v=OxCwFU0LhKI&t=380s), [08:44](https://www.youtube.com/watch?v=OxCwFU0LhKI&t=524s) | 铺垫生理前提；对比表逐行填入；共有表现先出，C 肽为核心鉴别，最后给出促泌剂筛查项 |
| **Light's Criteria** | `aGXfbIe7tH4` | 875 | 06:25 | [00:46](https://www.youtube.com/watch?v=aGXfbIe7tH4&t=46s), [02:18](https://www.youtube.com/watch?v=aGXfbIe7tH4&t=138s), [03:51](https://www.youtube.com/watch?v=aGXfbIe7tH4&t=231s), [06:10](https://www.youtube.com/watch?v=aGXfbIe7tH4&t=370s) | 概念压成直接联想；同一张阈值表停留数分钟；结尾增加“任一满足即渗出”解释列 |
| **Court Cases with Visual Mnemonics** | `PKn6Mzci_Bg` | 1918 | 12:20 | [01:52](https://www.youtube.com/watch?v=PKn6Mzci_Bg&t=112s), [02:17](https://www.youtube.com/watch?v=PKn6Mzci_Bg&t=137s), [03:25](https://www.youtube.com/watch?v=PKn6Mzci_Bg&t=205s), [03:38](https://www.youtube.com/watch?v=PKn6Mzci_Bg&t=218s) | 先说明案件事实与法律后果，随后展示联想图；指示箭头标明对应人名与判例内容 |
| **Question #37** | `uu9S5rXzJXA` | 1363 | 07:36 | [01:05](https://www.youtube.com/watch?v=uu9S5rXzJXA&t=65s), [01:20](https://www.youtube.com/watch?v=uu9S5rXzJXA&t=80s), [01:40](https://www.youtube.com/watch?v=uu9S5rXzJXA&t=100s), [03:10](https://www.youtube.com/watch?v=uu9S5rXzJXA&t=190s), [03:45](https://www.youtube.com/watch?v=uu9S5rXzJXA&t=225s), [04:25](https://www.youtube.com/watch?v=uu9S5rXzJXA&t=265s) | 原题先无标记呈现；提示自主暂停；题干关键条件变色高亮；在原题旁逐项写出干扰项排除依据 |
| **Question #56** | `btrxzxlQcL8` | 1347 | 08:02 | [00:57](https://www.youtube.com/watch?v=btrxzxlQcL8&t=57s), [01:55](https://www.youtube.com/watch?v=btrxzxlQcL8&t=115s), [04:49](https://www.youtube.com/watch?v=btrxzxlQcL8&t=289s), [05:03](https://www.youtube.com/watch?v=btrxzxlQcL8&t=303s), [05:10](https://www.youtube.com/watch?v=btrxzxlQcL8&t=310s), [06:20](https://www.youtube.com/watch?v=btrxzxlQcL8&t=380s) | 同一病例改变设问；保留未揭晓选项，先定解题准则再标答案；强调先后限定条件 |
| **TACO vs. TRALI** | `dFbeksvXh4g` | 668 | 04:39 | [00:33](https://www.youtube.com/watch?v=dFbeksvXh4g&t=33s), [01:07](https://www.youtube.com/watch?v=dFbeksvXh4g&t=67s), [02:14](https://www.youtube.com/watch?v=dFbeksvXh4g&t=134s), [03:21](https://www.youtube.com/watch?v=dFbeksvXh4g&t=201s), [04:28](https://www.youtube.com/watch?v=dFbeksvXh4g&t=268s) | 一条机制讲透后以同构画面展开另一条；共享肺水肿终点，聚焦血压与容量状态的鉴别 |

---

## 3. 原课已查证科学疏漏校正标准

制作新内容时，必须吸收教学结构优点，纠正原视频中存在的具体科学疏漏：

### 1. 依前列醇（Epoprostenol）药理作用属性核验
- **原课错误记录**：花生四烯酸代谢课（`Wz8OwDVvyJ0` 约 11:10–11:15）口播与幻灯片将依前列醇（Epoprostenol）标注为“抑制 PGI2”。
- **事实纠正**：依前列醇（Epoprostenol）本身是人工合成的前列环素（Prostacyclin / PGI2），临床用于治疗肺动脉高压。其药理机制为直接激动前列环素受体，引起强效的血管扩张与血小板聚集抑制，绝非 PGI2 抑制剂。
- **核验依据**：[NLM DailyMed 药品说明书](https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=47f64fcd-cbf7-457a-9548-661fb10ff7e0)。药理机制必须核查分子属于激动剂/类似物还是抑制剂。

### 2. Light 诊断标准阈值的数学逻辑
- **原课错误记录**：Light 诊断标准课（`aGXfbIe7tH4` 约 03:20 与 04:35）中，讲者将“胸水/血清蛋白比值 >0.5”口误解释为“分子大于分母”，对 LDH 比值 >0.6 亦作相同口述。
- **事实纠正**：比值为 0.6 时，0.6 > 0.5 满足渗出液阈值，但 0.6 < 1.0，分子（胸水蛋白浓度）仍然小于分母（血清蛋白浓度）。
- **核验依据**：比值指标必须严格表述为“超过诊断分界阈值”，不可解释为胸水浓度高于血清浓度。

### 3. 剥离绝对化应试修辞（修辞风格调整，非第 3 项事实错误）
- **原课风格观察**：原片存在“考场上只要见到这个词，永远不要选某项检查”“一秒都不犹豫”等主观应试口吻。
- **调整标准**：此类修辞属于个人应试夸张风格，不符合循证医学原则。处置方案的选择取决于具体适应证、禁忌证与题干约束。制作新课时，将绝对化断言转译为客观限定逻辑，不随意增添未经查证的临床指令。

---

## 4. 补充权威文献与公共数据库核准标准

- **谷胱甘肽过氧化物酶 (GPx)**：EC 1.11.1.9，催化 $2\text{ GSH} + \text{H}_2\text{O}_2 \rightarrow \text{GSSG} + 2\text{ H}_2\text{O}$（[IUBMB Enzyme Nomenclature](https://iubmb.qmul.ac.uk/enzyme/EC1/11/1/9.html)）。
- **谷胱甘肽还原酶 (GR)**：EC 1.8.1.7，催化 $\text{GSSG} + \text{NADPH} + \text{H}^+ \rightarrow 2\text{ GSH} + \text{NADP}^+$（[IUBMB Enzyme Nomenclature](https://iubmb.qmul.ac.uk/enzyme/EC1/8/1/7.html)）。
- **G6PD 缺乏症**：[MedlinePlus: G6PD deficiency](https://medlineplus.gov/genetics/condition/glucose-6-phosphate-dehydrogenase-deficiency/)。G6PD 催化生成 NADPH；缺乏者平时多无明显症状，在感染、特定药物或蚕豆等氧化压力下可诱发急性溶血。
- **咬痕细胞 (Bite cell)**：[ASH Image Bank #3820](https://imagebank.hematology.org/image/3820/bite-cell--1)。外周血涂片咬痕细胞形态。网页注明 Heinz 小体可用超活染色显示，但图片本身染色未注明；本地未下载该素材，分镜中注明待获取，先采用矢量机制图呈现。
- **C 肽检测 (C-peptide)**：[MedlinePlus: C-peptide test](https://medlineplus.gov/lab-tests/c-peptide-test/)。内源胰岛素分泌伴生 C 肽；商业注射胰岛素制剂不含 C 肽。
- **化脓性关节炎与晶体鉴别**：[SANJO Guidelines 2023 (J Bone Jt Infect, 8, 29-37)](https://jbji.copernicus.org/articles/8/29/2023/)。指南明确指出：发热不是化脓性关节炎的必需诊断标准（第 1 项）；关节滑液中检出晶体不能排除合并感染（第 5 项）。解题推理中严禁使用“无发热”或“有晶体”直接作为排除化脓性关节炎的绝对硬依据。
