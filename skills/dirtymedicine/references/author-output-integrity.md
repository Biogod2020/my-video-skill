# agy 讲稿输出完整性与版本校验规范

本规范用于固化讲稿撰写与修订环节的工程校验流程，确保 agy 产出的最新修订准确进入初学者审核、配音与成片流水线，防止调用包装层旧载荷静默覆盖新稿。

---

## 1. 核心校验原则与防御策略

1. **背景与防御定位**：
   - 偶发流程缺陷表明：agy 的当前 final response 中已生成新修订稿，但外层 JSON envelope 中的 `structured_output`（或旧 tool payload）仍残留旧稿。若调用封装盲目优先读取 `structured_output`，会导致最新修订丢失，审核与配音仍沿用旧稿。
   - 此问题属于特定包装环境的载荷滞后，不泛化认定为所有服务必然错误；但工程层面必须建立确定性防御，绝不依赖包装层默认假设。
2. **私下保留原始响应**：
   - 必须私下完整保存原始响应 envelope（含可用的模型正文、tool call 记录及原始 payload；不得保存认证请求头、Cookie 或密钥），用于工程审计与问题追溯；严禁在公开 skill 中泄露私有数据。
3. **解析最终正文与 Schema 独立校验**：
   - 优先解析当前最终 response JSON，并由工程执行独立的 JSON Schema 校验（依赖 `jsonschema`）。
   - 严格比较 final response 与 `structured_output` 两份输出，分别计算哈希，记录差异并显式登记选择来源（`result_source: "current final response JSON"`，并记录 `structured_output_used: false`）。两者不同时必须记录核查线索。
4. **硬性阻断与禁止静默回退**：
   - 若 final response 无效、字段残缺（如缺失必要教学字段）或包含多份冲突 JSON，必须立即硬性退出并阻断流程；**绝对禁止静默回退到旧 structured_output**。
   - 真实样本已验证此机制能可靠选出最新稿件，并有效拦截残缺或多份冲突 JSON。
5. **实质修订变更确认（`--require-change`）**：
   - 针对明确要求实质修改的任务，与前版讲稿（`--previous`）进行差异检查，确认确有预期修改。
   - **仅在用户明确请求实质修订时启用 `--require-change`**；正常审稿或无问题稿件绝不强迫为了换词而换词。
6. **质量与身份解耦**：
   - 哈希仅代表版本身份，JSON Schema 通过仅代表结构合规；**严禁将 hash 变化等同于质量变好，严禁将 schema 校验通过等同于初学者口语易懂**。
   - 讲稿语义与教学质量仍坚决依赖独立的初学者复述审核（[learner-review.md](learner-review.md)）、全库对照及人工/模型听看多模态验收。

---

## 2. 工程校验接口与规约

### 2.1 CLI 调用命令
```bash
python scripts/verify_agy_result.py \
  --response response.json \
  --schema schema.json \
  --previous old.json \
  --require-change \
  --out verified/
```

### 2.2 实现架构与产物规则
- **内部模块**：由 `scripts/agy_result.py` 提供响应提取、JSON 解析与比对 helpers，依赖 `jsonschema` 执行 Schema 验证。
- **输出产物**：
  - `result.json`：通过校验并规范化的最终讲稿。
  - `checks.json`：记录 Schema 校验状态、版本哈希比对、选择来源（实际字段 `result_source` 与 `structured_output_used`）及与上一版的变更详情。
- **失败严禁产出**：若 Schema 校验失败、检测到多份冲突 JSON、字段残缺或 `--require-change` 未检出预期变化，脚本必须立即非零退出，**严禁在 `--out` 目录下生成可用的 `result.json`**，防止下游错误消费。

---

## 3. 全链路版本身份追踪（Hash Chain）

为防止审核或配音环节混淆新旧版本，建立全生命周期的哈希追踪链：

$$\text{writer 最终稿 hash} \longrightarrow \text{规范讲稿 hash} \longrightarrow \text{审核语言 hash} \longrightarrow \text{tts\_input hash} \longrightarrow \text{最终 mediahash}$$

1. **链路逐项确认**：
   - `writer 最终稿 hash`：agy 最终产出的原始文本/JSON 哈希。
   - `规范讲稿 hash`：经 `verify_agy_result.py` 校验放行后的结构化讲稿哈希。
   - `审核语言 hash`：进入初学者复述与全库对照的单语言结构哈希（如 `draft_language_sha256`）。
   - `tts_input hash`：送入 MOSS-TTS 的最终发音台词哈希（医学专有名词经显式发音映射后的真实送读文本；教学停顿标记属于元数据，须先剥离，不发给 TTS）。
   - `最终 mediahash`：最终导出的母带音频及封装 MP4 文件的 SHA256 哈希。
2. **重算版本身份与禁止移植 PASS**：
   - 凡讲稿发生任何实质变更，受影响的初学者审核、逐段对照、配音输入及成片必须全量重算对应版本身份。
   - **严禁向新版本哈希移植旧版本的模型 PASS 记录**，确保每份成品的验收证据与实际交付内容严格对齐。
3. **工程确定性计算**：
   - 数值哈希与 Schema 校验由工程脚本独立完成，无需且严禁额外调用 Gemini 决策或等待批准。
4. **素材授权与语音参数延续**：
   - 严格遵循用户既有的相同素材长期授权；配音底模、LoRA 权重配置、参考音及 continuation 前缀参数保持既有冻结标准不变。

---

## 4. 脱敏示例数据（checks.json）

> [!NOTE]
> 公开规范中严禁包含任何私人全稿、真实音频、本机绝对路径或私有实际哈希。以下仅使用虚拟脱敏示例说明结构：

```json
{
  "state": "passed",
  "model_called": false,
  "result_source": "current final response JSON",
  "json_schema_validated": true,
  "structured_output_present": true,
  "structured_output_matches_final": false,
  "structured_output_used": false,
  "final_response_sha256": "<private-record>",
  "selected_result_sha256": "<private-record>",
  "structured_output_sha256": "<private-record>",
  "previous_result_sha256": "<private-record>",
  "requested_change_observed": true
}
```

`requested_change_observed` 只表示与前版结构内容不同，不证明改动有意义或质量提高。生产讲稿的 Schema 必须实际提供并校验；未提供时 `json_schema_validated=false`，不得当作结构验收通过。
