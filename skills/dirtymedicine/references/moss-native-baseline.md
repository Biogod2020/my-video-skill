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
2. **稀疏剪辑派生母带**：经用户授权，仅在完成句意、机制转折、看图引导或正式题处按需补足认知留白。必须在波形确认的纯安静中心补差，严禁裁剪呼吸、严禁切断词句，保留源 PCM 顺序，不逐句/逐页机械加白；仅为加留白不重生成发声片段，另有局部改稿请求时按受影响上下文单列修复派生版。
3. **时序重算与回滚管理**：派生母带基于 sample 级 EDL 构建，字幕、动态高亮、章节轴与倒计时全部依一套映射重算；字幕展示随教学需要保留，题页严禁提前泄露答案。派生版本可随时无损回滚至原生母带。
4. **封装与审核状态**：视频渲染直接封装已审最终母带，渲染器严禁二次加工。制作、工程验证、Gemini 听审与用户接受分别记录，未执行的步骤不得标为完成。最终完整长音频独立盲听，完整 MP4 实看实听；调用用户指定的 `gemini-3.8-flash-high` 并分别记录 requested/returned model、实际附件 hash 与视觉采样设置。工程验证独立完成，不把模型自述当成逐帧或波形验真。
