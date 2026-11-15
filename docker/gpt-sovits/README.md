# GPT-SoVITS Docker 服务（legacy，可选）

本目录保留旧的 GPT-SoVITS 推理服务，作为 **legacy** 方案。v2 默认 TTS 已切到 IndexTTS-2.5 sidecar（`http://127.0.0.1:9882`）；只有显式设置 `TTS_PROVIDER=gpt_sovits` 时后端才会调用这里。

- 推理 API：`http://127.0.0.1:9880/`
- 容器名：`virtual-original-bot-gpt-sovits`
- 镜像：`xxxxrt666/gpt-sovits:latest-cu126-lite`（CUDA 12.6）
- 默认不启动 WebUI；镜像当前存在 Gradio/Jinja2 兼容问题

## 1. 启动与停止

在仓库根目录执行（PowerShell）：

```powershell
Set-Location <仓库根>\docker\gpt-sovits
docker compose up -d
docker compose logs -f gpt-sovits
```

停止：

```powershell
Set-Location <仓库根>\docker\gpt-sovits
docker compose down
```

需要实验性 WebUI 时（端口 `9872`，默认不可用）：

```powershell
docker compose --profile webui up -d gpt-sovits-webui
```

## 2. 切换到 legacy provider

后端默认不调用 GPT-SoVITS。编辑 `backend/.env`：

```dotenv
TTS_PROVIDER=gpt_sovits
GPT_SOVITS_BASE_URL=http://127.0.0.1:9880/
GPT_SOVITS_TIMEOUT_SECONDS=180
```

然后重启后端。切回默认：

```dotenv
TTS_PROVIDER=index_tts
INDEX_TTS_BASE_URL=http://127.0.0.1:9882
```

`TTS_PROVIDER` 只接受 `index_tts` / `gpt_sovits`；其他值会让后端在启动时直接报错，不会静默降级。

## 3. 路径映射

`docker-compose.yml` 把本目录挂到容器 `/workspace`：

| 宿主机（`docker/gpt-sovits/` 下） | 容器内 | 内容 |
| --- | --- | --- |
| `./models` | `/workspace/models` | 预训练、微调权重、G2PW、ASR、UVR5 |
| `./data` | `/workspace/data` | 参考音频与输出 |

容器启动命令使用以下容器内路径：

```text
/workspace/models/custom/murasame_v2_e6_s6450.pth   # SoVITS 微调权重
/workspace/models/custom/murasame_v2-e4.ckpt        # GPT 微调权重
/workspace/models/pretrained_models/                # 预训练模型
/workspace/models/G2PWModel/                        # G2PW
/workspace/models/asr_models/                       # ASR（训练/工具用）
/workspace/models/uvr5_weights/                     # UVR5（训练/工具用）
/workspace/data/references/murasame_ref.ogg         # 内置参考音频
/workspace/data/outputs/                            # 输出目录
```

`models/`、`data/outputs/`、`training/logs/` 都在 `.gitignore` 中，不随仓库分发。首次运行前需要把权重与参考音频放到对应位置，否则容器会因找不到文件退出。

## 4. 后端如何发送请求

后端的 `GptSovitsProvider`（`backend/app/models/tts/gpt_sovits.py`）把音色档案的 `gpt_sovits` 段映射为 legacy payload：

```json
{
  "refer_wav_path": "/workspace/data/references/murasame_ref.ogg",
  "prompt_text": "はっはっはっは",
  "prompt_language": "ja",
  "text": "こんにちは。",
  "text_language": "zh"
}
```

- `refer_wav_path` / `prompt_text` / `prompt_language` 是**容器内路径与文本**，只对 legacy provider 有意义；IndexTTS 会忽略它们。
- 这些值来自 `backend/config/voices.json`（内置档案）或 `backend/runtime/voices/profiles.json`（用户档案）的 `gpt_sovits` 段，代码里不再硬编码 `/workspace`。
- `text_language` 由档案 `language` 映射（`ZH→zh`、`EN→en`、`JA→ja`、`ES→es`、`AR→ar`），也可以在 `gpt_sovits.text_language` 显式覆盖。
- `prompt_text` 必须与参考音频实际内容一致；不一致会明显影响音色与发音。
- 用户通过 `POST /voices` 克隆的档案默认没有 `gpt_sovits` 段，legacy provider 会退回请求里的宿主机参考音频绝对路径；容器通常读不到该路径，因此 legacy 模式下应为每个音色补上容器内映射。

直接用 `curl` 验证：

```powershell
$body = @{
  refer_wav_path = "/workspace/data/references/murasame_ref.ogg"
  prompt_text = "はっはっはっは"
  prompt_language = "ja"
  text = "こんにちは。"
  text_language = "ja"
} | ConvertTo-Json

Invoke-WebRequest -Uri http://127.0.0.1:9880/ -Method Post `
  -ContentType "application/json" -Body $body -OutFile legacy.wav
```

成功返回 WAV 字节；失败由后端映射为 `tts.failed{code:"tts_unavailable"}`（HTTP `/tts` 则为 `503`）。

## 5. 当前权重与数据

- GPT 微调权重：`models/custom/murasame_v2-e4.ckpt`
- SoVITS 微调权重：`models/custom/murasame_v2_e6_s6450.pth`
- 预训练模型：`models/pretrained_models/`
- G2PW：`models/G2PWModel/`
- 参考音频：`data/references/murasame_ref.ogg`
- 输出：`data/outputs/`

`murasame_ref.ogg` 对应训练切片 `mur303_062_ref.wav`，台词是 `はっはっはっは`（笑声）。它作为参考音频并不理想；正式使用时建议换成一段 5–8 秒的正常日语对白切片。

## 6. 训练流程

GPT-SoVITS 的训练流程与数据集不搬入本仓库；`training/` 只保留旧数据集清单与审计产物（`murasame.list`、`kept.txt`、`dropped*.txt`），训练脚本位于 `scripts/`，是否可复现取决于本地旧目录与权重。数据集质量问题见 [`../../docs/murasame-dataset-audit.md`](../../docs/murasame-dataset-audit.md)。

## 7. 与 IndexTTS 的选择

| 维度 | IndexTTS-2.5（默认） | GPT-SoVITS（legacy） |
| --- | --- | --- |
| 端口 | 9882 | 9880（WebUI 9872） |
| 部署 | 本地 Python sidecar + index-tts `.venv` | Docker + CUDA 镜像 |
| 克隆方式 | 参考音频零样本 | 参考音频 + prompt（legacy）或微调权重 |
| 后端配置 | `TTS_PROVIDER=index_tts` | `TTS_PROVIDER=gpt_sovits` |
| 参考音频路径 | 宿主机绝对路径 | 优先使用档案 `gpt_sovits.refer_wav_path`（容器内） |
| 情感向量 | 支持 `vector` / `audio`；`text` 缺 QwenEmotion | legacy payload 不传情感 |

8GB 显存下两者都不适合与 Ollama 同时占 GPU；跑 TTS 时建议 `OLLAMA_NUM_GPU=0`。

## 8. 排障

| 现象 | 排查 |
| --- | --- |
| 容器反复重启 | `docker compose logs gpt-sovits`；多为权重/参考音频路径缺失 |
| `9880` 连不上 | 容器是否 `Up`、端口是否被占用、Docker Desktop 是否运行 |
| 合成报 `tts_unavailable` | 容器日志、`GPT_SOVITS_BASE_URL` 是否带对端口、`refer_wav_path` 是否是容器内路径 |
| 声音不对/念错 | `prompt_text` 与参考音频不一致，或参考音频质量差 |
| WebUI 起不来 | 已知 Gradio/Jinja2 兼容问题，默认不启用 |
| 显存不足 | 关闭其他 GPU 程序；GPT-SoVITS 与 IndexTTS 不要同时跑 |

## 9. 许可

- GPT-SoVITS 代码与镜像遵循上游许可；预训练/微调权重、参考音频与训练数据各自受其许可约束。
- 本仓库不附带权重与训练数据；使用前请确认你有权使用相应模型与声音。
