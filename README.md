# dirtymedicine

借鉴 Dirty Medicine 教学法设计医学口播讲稿与分镜方案（v2.26）。

## 仓库布局与安装

技能完整目录为 `skills/dirtymedicine/`，包含 `SKILL.md`、`agents/openai.yaml`、配套参考文档、可复用校验脚本与测试。

安装：将 `skills/dirtymedicine/` 完整目录复制到项目的 `.agents/skills/dirtymedicine` 或用户全局的 `.codex/skills/dirtymedicine`。

## 核心文档

- [SKILL.md](skills/dirtymedicine/SKILL.md)：技能主入口。
- [口诀设计与视觉联想](skills/dirtymedicine/references/mnemonic-authoring.md)：助记法创作与独立审核规范。
- [教学叙事与承接](skills/dirtymedicine/references/narrative-flow.md)：建立开篇动机与自然跨段转场，避免教案报幕腔。
- [教学因果闭环](skills/dirtymedicine/references/learning-closure.md)：冻结核心问题，检查“缺陷 → 动作 → 后果”的因果链及仅凭当前讲稿的独立审核；配套校验脚本与 Schema 已纳入讲稿审核门禁。
- [批量讲稿生成与定标质检](skills/dirtymedicine/references/batch-authoring.md)：双语篇幅预算、20 项验收与有限返修规范。文中批量控制器依赖本机课程生产项目，不包含在此技能目录内。

## 发布范围

随仓库提供技能规范、可复用校验脚本与测试。付费课程全文、原始项目记录、私人参考录音与凭证不随仓库发布。
