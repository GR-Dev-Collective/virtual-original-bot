# 丛雨 GPT-SoVITS 重训

重训流程与配置。数据集为什么重建、重建效果如何，见 [`docs/murasame-dataset-audit.md`](../../../docs/murasame-dataset-audit.md)。

## 为什么不在 Docker 里训练

推理用 Docker 是对的，训练不是。训练要读写已有的预处理缓存（`4-cnhubert`、`6-name2semantic`）
和预训练权重，而本机已有一套验证过的环境 —— 现有权重就是它产出的：

```text
voice_clone_project/.gpt-sovits-venv    408 个包，Python 3.10.11
```

用 Docker 重建同样的环境只会引入额外的不确定性，收益为零。推理侧继续用
`docker/gpt-sovits/docker-compose.yml`，两者互不影响。

## 前置

| 项 | 位置 |
|---|---|
| GPT-SoVITS 仓库 | `voice_cloning/GPT-SoVITS旧目录_暂存` |
| 训练解释器 | `voice_clone_project/.gpt-sovits-venv/Scripts/python.exe` |
| 训练清单 | `docker/gpt-sovits/training/murasame.list`（3886 条） |
| 音频切片 | `GPT-SoVITS旧目录_暂存/logs/murasame_v2/5-wav32k` |

预训练权重（`gsv-v2final-pretrained`）与 BERT / Hubert 模型都在仓库内，无需下载。

## 步骤

三个阶段分开跑，每步都可单独重入：

```powershell
python scripts/train_murasame.py --stage prepare
python scripts/train_murasame.py --stage sovits
python scripts/train_murasame.py --stage gpt
```

### prepare

- 用新清单重算文本音素（`1-get-text.py`）—— 文本变了，这一步必须重跑
- **复用**上次实验的音频侧缓存 `4-cnhubert` 与 `6-name2semantic-0.tsv`：
  它们只取决于音频，与文本无关，重算要花掉整个预处理里最贵的一段
- 补两件 GPT-SoVITS webui 才会做的事：
  1. 把分片 `2-name2text-{i}.txt` 合并成 `2-name2text.txt`
  2. 把语义表从 4367 条裁到 3886 条，与音素一致

跑完三个文件都应是 3886 行：

```text
logs/murasame_v3/2-name2text.txt          3886
logs/murasame_v3/2-name2text-0.txt        3886
logs/murasame_v3/6-name2semantic-0.tsv    3886
```

### sovits

`utils.get_hparams(stage=2)` 读的是 **JSON**（不是 yaml），配置由脚本生成到
`training/generated/`（已 gitignore，因为含本机绝对路径）。

这次沿用上次的参数（batch_size 4、8 轮、save_every_epoch 2），与上次一致，便于对比。

### gpt

`get_hparams(stage=1)` 同样读 JSON。**上次只训到 4 轮**，这次补到 **8 轮**
（`S1_CONFIG.train.epochs`）——这是与上次最主要的差异，也是最直接的改进点。

## 产物

- SoVITS 权重 -> `GPT-SoVITS旧目录_暂存/SoVITS_weights_v2/murasame_v3_*.pth`
- GPT 权重 -> `GPT-SoVITS旧目录_暂存/GPT_weights_v2/murasame_v3-*.ckpt`
- 训练日志 -> `GPT-SoVITS旧目录_暂存/logs/murasame_v3/`

脚本会拒绝 `--exp murasame_v2`，避免覆盖已有权重。参考对照：

| | 上次（murasame_v2） | 本次（murasame_v3） |
|---|---|---|
| 数据条目 | 4367（噪声标注） | 3886（已清洗） |
| SoVITS 轮数 | 8 | 8 |
| GPT 轮数 | **4** | **8** |

## 参考耗时

上次 SoVITS 每轮约 16 分钟，8 轮约 2 小时（RTX 4060 Laptop）。GPT 侧按同样量级估计。

## 训练完成后

1. 用新权重替换 `docker/gpt-sovits/docker-compose.yml` 里的 `-s` / `-g` 路径
2. 重启推理容器，用同一段文本做新旧 A/B 对比
3. 顺带换掉参考音频：现在的 `murasame_ref.ogg` 是一段笑声切片，不适合做提示
