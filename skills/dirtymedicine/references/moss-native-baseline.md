# MOSS-TTS 英文原生基线与派生母带规范

本规范定义英文医学长课 MOSS-TTS-v1.5 8B 底模原生连续生成基线及剪辑派生母带管理标准。

## 1. 英文默认生成基线与参数

英文长课默认使用底模原生连续生成（`adapter_loaded=false`），不加载 LoRA adapter；中文课程已验证的 LoRA 权重保持独立有效。沿用已授权同一参考声与既有英文教师 continuation 前缀（约 20 秒，251 frames），一次原生生成整轨长音频（B02 实测 13:54 / 833.76s），实际 `Instruction=None`（严禁将教学目标元数据误写为模型风格指令）。

| 参数项 | 基线配置值 | 说明 |
|---|---|---|
| 模型 / Codec Revision | `cdd3b911b1585e3f2dbc7775ef10f9926f58850a` / `3cd226ba2947efa357ef453bcad111b6eafba782` | MOSS-TTS-v1.5 8B base 与匹配 codec |
| Adapter / Seed / 采样率 | `false` / `42` / `24000 Hz` | 无英文 LoRA，固定种子，统一采样率 |
| Audio Sampling | T=1.7, top_p=0.8, top_k=25, rep_penalty=1.0 | 音频码本采样参数 |
| Text Sampling | T=1.5, top_p=1.0, top_k=50 | 文本采样参数 |
| 时长条件与 Cap (B02 案例) | duration tokens: 11532, max_new_tokens: 13500 | 软引导与步数上限，非普适常数 |

**时长预算动态计算**：B02 案例目标 902.47 秒与 11532 tokens 仅属于本讲文稿与前缀的软性引导预算；后续新课程必须将正文纯发声预算与实测原生静音余量分开估计，再把前缀帧数计入时长条件；安全步数上限另行计算，严禁作为普适硬常数固化。说明可复现输入与配置，不保证跨硬件位级比特相同。

## 2. 私有 Recipe 记录 Schema

项目私有日志按以下规范结构记录生成环境与参数，严禁公开私人录音源文件、真实参考音 Hash 或绝对本机路径：
```json
{
  "job": { "id": "B02-en-base-matched-s42", "variant": "base", "seed": 42 },
  "model_revision": "cdd3b911b1585e3f2dbc7775ef10f9926f58850a",
  "codec_revision": "3cd226ba2947efa357ef453bcad111b6eafba782",
  "adapter_loaded": false,
  "settings": { "audio_temperature": 1.7, "audio_top_p": 0.8, "audio_top_k": 25, "audio_repetition_penalty": 1.0, "text_temperature": 1.5, "text_top_p": 1.0, "text_top_k": 50 },
  "duration_condition": { "tokens": 11532 },
  "max_new_tokens": 13500,
  "hashes": { "text_sha256": "...", "reference_sha256": "<private>", "prefix_audio_sha256": "<private>", "prefix_text_sha256": "...", "input_ids_sha256": "...", "engine_sha256": "...", "dependency_lock_sha256": "...", "output_audio_sha256": "..." },
  "environment": { "gpu": "NVIDIA A100-SXM4-40GB", "attention": "sdpa" }
}
```

## 3. TTS 原生母带与稀疏留白派生母带

1. **TTS 原生母带**：发声与自然停连经用户认可即为原生母带，默认无全局 tempo 变速、无逐句时间拉伸、无逐逗号静音标准化；工程测速筛查仍持续运行，但线索不自动机械套改。
2. **稀疏剪辑派生母带（英文最新偏好规范）**：英文根据用户最新明确反馈，默认保留整轨原生停连和语流，工程默认 `application_mode=candidates_only`（输出零 edits identity EDL，音频原 PCM 逐样本不变，仍可统一驱动字幕/画面）。严禁按句号、换页、所谓认知点或固定秒数补齐；旧 policy 的 `target_gap_seconds`、`[pause Xs]` 或语义标注不再自动授权补足；题前可按需补白，但不自动把所有题补到 4 秒，“Pause your screen”亦不代表必须塞长静音。仅在显式声明 `application_mode=necessary_only` 且边界逐一标有 `necessary_edit:true` 与非空 `necessity_reason`（例如问句确实抢入答案、听众确实来不及看关键图，经真实前后音频复核确有缺口且通过波形静音检查）时才允许剪辑派生；已有自然停顿足够、不补更连贯、无明确问题时允许全课 0 次剪辑。中文原有 `annotated_boundaries` 默认保留，同样不鼓励机械补白，但本次不改其中文既有默认工程方式。
3. **时序重算与听感排查回滚**：派生母带基于 sample 级 EDL 构建，字幕、动态高亮、章节轴与倒计时全部依一套映射重算；字幕展示随教学需要保留，题页严禁提前泄露答案。派生版本可随时无损回滚至原生母带。当用户反馈语流不顺或停顿生硬时：
   - **严格区分后期插入与原生气口**：先检查 EDL，准确区分后期插入静音与 TTS 原生气口（例如 B-01 锚点处不顺实为原生 CTC 2.86 秒间隔，此前误删两题 3.76 秒后期补白未解决目标处问题；不可从听感反推所有长气口都是后期造成）；
   - **回滚与原生过长缩短分流**：若属后期插入问题优先回滚；但必须澄清“原生”不代表“天然自然”，经实听确认的原生过长静音可按需缩短，保护的是发声和呼吸而非冻结所有原生空隙。发声音色已认可时无需重跑 TTS，依 [references/english-gap-audit.md](english-gap-audit.md) 进行全轨扫描、实听复核与局部安全缩短；
   - **双版留存与用户审核**：完整保留原版与回滚/新派生版，经 Gemini 全量实听实看并获用户审核确认后，方可更新已公开视频。
4. **封装与审核状态**：视频渲染直接封装已审最终母带，渲染器严禁二次加工。制作、工程验证、Gemini 听审与用户接受分别记录，未执行的步骤不得标为完成。最终完整长音频独立盲听，完整 MP4 实看实听；调用用户指定的 `gemini-3.8-flash-high` 并分别记录 requested/returned model、实际附件 hash 与视觉采样设置。工程验证独立完成，不把模型自述当成逐帧或波形验真。
