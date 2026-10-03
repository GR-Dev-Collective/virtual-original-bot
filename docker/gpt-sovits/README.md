# GPT-SoVITS Docker 服务

这个目录提供 `virtual-original-bot` 使用的 GPT-SoVITS 独立推理服务。

## 启动

在 PowerShell 中执行：

```powershell
Set-Location 'C:\Users\chen\Desktop\projects\virtual-original-bot\docker\gpt-sovits'
docker compose up -d
```

服务地址：

- 推理 API：`http://127.0.0.1:9880/`
- WebUI：默认不启动；镜像当前存在 Gradio/Jinja2 兼容问题
- 如需实验性启动 WebUI：`docker compose --profile webui up -d gpt-sovits-webui`，端口为 `http://127.0.0.1:9872/`

## 查看日志

```powershell
docker compose logs -f gpt-sovits
```

## 停止

```powershell
docker compose down
```

## 当前模型

- CUDA 镜像：`xxxxrt666/gpt-sovits:latest-cu126-lite`
- 推理设备：CUDA
- GPT 微调权重：`models/custom/murasame_v2-e4.ckpt`
- SoVITS 微调权重：`models/custom/murasame_v2_e6_s6450.pth`
- 预训练模型：`models/pretrained_models/`
- G2PW 模型：`models/G2PWModel/`
- 参考音频：`data/references/murasame_ref.ogg`
- 输出目录：`data/outputs/`

API 请求使用容器内路径。例如：

```json
{
  "refer_wav_path": "/workspace/data/references/murasame_ref.ogg",
  "prompt_text": "はっはっはっは",
  "prompt_language": "ja",
  "text": "こんにちは。",
  "text_language": "ja"
}
```

> 注意：`prompt_text` 必须和参考音频内容一致。

`murasame_ref.ogg` 对应训练切片 `mur303_062_ref.wav`，台词为 `はっはっはっは`（笑声）。它作为参考音频并不理想，建议后续换成一段 5～8 秒的正常日语对白切片再用于正式推理。

## 数据说明

旧版本地 GPT-SoVITS 目录没有删除，而是移动到：

```text
C:\Users\chen\Desktop\GPT-SoVITS旧目录_暂存
```

Docker 数据和模型现在独立保存在本目录中。
