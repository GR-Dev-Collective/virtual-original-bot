# 音色参考音频

本目录存放随仓库分发的**内置音色**参考音频，以及音色目录约定说明。

## 目录约定

```text
assets/voices/
└─ <voice_id>/
   └─ <voice_id>_ref.wav
```

- `<voice_id>` 必须匹配 `[a-z0-9_-]{1,64}`（与 `VoiceProfile.id` 一致）。
- 参考音频文件名固定为 `<voice_id>_ref.wav`，便于构建 `backend/config/voices.json` 中的相对路径。
- 内置音色 `murasame`（丛雨）对应：

```text
assets/voices/murasame/murasame_ref.wav
```

`backend/config/voices.json` 里的 `reference_audio` 相对**仓库根**解析，因此写作 `assets/voices/murasame/murasame_ref.wav`。不要写本机绝对路径，也不要依赖某个用户的 home 目录。

## 参考音频要求

后端（`POST /voices`）会做统一规范化，但源文件仍应满足：

- **时长 1–60 秒**（不足或超出会被拒绝）；
- 单人、干净人声，尽量无背景音乐、噪声、混响和削波；
- 建议 3–15 秒；16-bit PCM 单声道 WAV 最稳妥；
- 任意 PyAV/FFmpeg 可解码的容器都可上传；WAV 保留原采样率，其他格式统一转 44.1kHz；
- 参考音频只决定音色，不要求与合成文本同语言；发音语言由音色档案的 `language` 指定。

## 用户克隆音频不写这里

用户通过 `POST /voices` 上传的参考音频**不会**写入本目录，而是规范化后保存到：

```text
backend/runtime/voices/<voice_id>/reference.wav
```

以及档案文件：

```text
backend/runtime/voices/profiles.json
```

`backend/runtime/` 已被 `.gitignore` 忽略，不会误提交。新增内置音色才需要把参考音频放进 `assets/voices/`，并同步修改 `backend/config/voices.json`。

## 授权与合规

- **只提交你有权分发的音频。** 把参考音频放进本目录意味着它会随仓库分发；请确认你拥有相应授权，或使用明确允许再分发的素材。
- **克隆真实人物声音需要本人同意。** 未经授权克隆他人声音可能侵犯人格权/声音权益，或违反平台条款。使用者应自行保存授权证明。
- `murasame` 参考音频仅用于本地技术原型的示例；角色与音频的权利归原权利人，不构成对外商用或再分发授权。
- IndexTTS-2.5 模型、GPT-SoVITS 权重与 Live2D 素材分别受其上游许可约束；本仓库不附带模型权重。

## 相关文档

- [`../../docs/VOICE_CLONING.md`](../../docs/VOICE_CLONING.md)：克隆流程、音色档案字段、情感/语速、sidecar API 与许可。
- [`../../backend/config/voices.json`](../../backend/config/voices.json)：内置音色档案。
- [`../../shared/contracts/protocol.md`](../../shared/contracts/protocol.md)：`voice.select` / `voice.selected` 协议。
