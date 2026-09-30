# virtual-original-bot

虚拟机器人原型机：一个基于 Electron、FastAPI 和多模态模型的桌面虚拟角色项目。

项目目标是让虚拟角色能够通过文本、语音和视觉输入理解用户，并通过语音、Live2D 表情、情绪状态和可控动作进行反馈。

当前项目处于原型搭建阶段。现阶段优先验证 Electron 与 FastAPI 的通信边界，再逐步接入 ASR、LLM、TTS、Vision、Memory 和 Action 等模块。

## 当前状态

当前仓库已经包含：

- 后端分层骨架：`backend/app/`，含控制通道 WebSocket `/ws/control`
- 控制通道协议契约：`shared/contracts/`
- GPT-SoVITS 推理服务（Docker）：`docker/gpt-sovits/`
- Electron 桌面端：`apps/desktop/`

**Phase 1（Electron ↔ FastAPI 基础通信）**：后端一侧已完成并通过测试，前端 Electron 一侧正在搭建。

Whisper、LLM、Vision、OCR、Memory、Action 等能力属于后续规划模块，尚未在当前仓库中完成接入。

## 技术栈

### 前端

- Electron：桌面应用容器
- HTML / CSS / JavaScript：界面实现
- Live2D：虚拟角色展示与动作表现
- 后续可迁移到 TypeScript

### 后端

- FastAPI：HTTP API 和服务入口
- WebSocket：实时控制消息和状态推送
- `asyncio`：异步任务和并发处理
- Python：模型适配、Agent 编排和业务逻辑

## 当前目录结构

```text
virtual-original-bot/
├─ apps/desktop/                 # Electron 桌面端（electron-vite）
│  ├─ src/main/                  # 主进程：窗口与生命周期
│  ├─ src/preload/               # contextBridge 安全桥
│  └─ src/renderer/              # 界面与控制通道客户端（音频、Live2D 待实现）
│
├─ backend/                      # FastAPI 后端
│  ├─ app/
│  │  ├─ main.py                 # 应用装配
│  │  ├─ config.py               # 配置
│  │  ├─ transport/              # 控制通道与消息模型
│  │  ├─ agent/                  # Agent 决策与编排
│  │  ├─ state/                  # 会话状态
│  │  ├─ models/                 # 模型适配器与路由（规划）
│  │  ├─ memory/                 # 记忆（规划）
│  │  ├─ actions/                # 动作（规划）
│  │  └─ workers/                # 后台任务（规划）
│  └─ tests/
│
├─ shared/contracts/             # 前后端共享协议（schema + 说明）
├─ docker/gpt-sovits/            # GPT-SoVITS 推理服务
├─ docs/                         # 规划：架构与设计文档
├─ scripts/                      # 规划：启动、检查和构建脚本
├─ .gitignore
├─ LICENSE
└─ README.md
```

## 运行

### 后端

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8090
```

- 健康检查：`http://127.0.0.1:8090/health`
- 控制通道：`ws://127.0.0.1:8090/ws/control`

> 默认端口是 8090 而非 8080：本机 8080 被系统占用且无法绑定（bind 返回 WinError 10013）。可用 `backend/.env` 覆盖。

### 桌面端

```powershell
Set-Location apps\desktop
npm install
npm run dev
```

窗口底部输入文本并回车，后端会回一条 `agent.text`。后端地址可用 `VOB_CONTROL_URL` 环境变量覆盖。

### GPT-SoVITS 推理服务

```powershell
Set-Location docker\gpt-sovits
docker compose up -d
```

### 测试

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest
```

## 目标架构

项目采用：

- Modular Monolith：模块化单体
- Layered Architecture：分层架构
- Event-driven：事件驱动
- Ports and Adapters：Ports and Adapters 架构

```text
┌─────────────────────────────────────────────────────────┐
│ Electron Desktop                                         │
│ UI / Live2D / Audio Input / Audio Output / User Actions  │
└───────────────────────┬─────────────────────────────────┘
                        │ Control WebSocket
                        │ Optional Voice WebSocket
┌───────────────────────▼─────────────────────────────────┐
│ FastAPI Backend                                           │
│ Transport / Session / Event Routing                       │
└──────────┬──────────────┬──────────────┬────────────────┘
           │              │              │
┌──────────▼──────┐ ┌─────▼────────┐ ┌───▼────────────────┐
│ Agent Core      │ │ Model Router │ │ Action Controller  │
│ 决策与编排       │ │ 模型适配与选择 │ │ 动作校验与执行      │
└──────────┬──────┘ └─────┬────────┘ └───────────────────┘
           │              │
┌──────────▼──────┐ ┌─────▼──────────────────────────────┐
│ Memory          │ │ ASR / TTS / LLM / Vision / OCR     │
│ 对话与长期记忆   │ │ Whisper / GPT-SoVITS / 其他模型适配器 │
└─────────────────┘ └────────────────────────────────────┘
```

## 输入与输出流程

### 音频输入

```text
麦克风 → VAD → ASR → Agent Core → LLM → TTS → 音频播放
```

- VAD：检测用户是否正在说话
- ASR：将语音转换为文本
- `interrupt`：在用户重新说话或主动操作时中断当前回复
- TTS：将回复文本转换为语音

### 文本输入

```text
键盘文本 → Agent Core → LLM → TTS 或文本回复
```

文本输入不经过 VAD 和 ASR。

### 视频输入

```text
摄像头/视频 → Video → Vision / OCR → State → Agent Core
```

视频应该先进行采样或抽帧，再交给 Vision 或 OCR 处理，避免持续把每一帧直接送入模型。

### 动作和角色表现

```text
Agent Core → Action Controller → 外部设备或系统动作
Agent Core → Emotion / State → Live2D 表情与动作
Agent Core → TTS → 音频播放
```

Agent Core 只负责决定行为，不直接操作设备。所有外部动作都经过 Action Controller 的注册、参数校验、执行和结果回传。

## 后端模块规划

以下目录是目标布局，不代表当前仓库已经全部实现：

```text
backend/
└─ app/
   ├─ main.py                    # FastAPI 启动入口
   ├─ transport/
   │  ├─ control_ws.py           # 控制、状态和事件消息
   │  └─ voice_ws.py             # 音频流通道
   ├─ agent/
   │  └─ agent_core.py           # Agent 决策和流程编排
   ├─ models/
   │  ├─ router.py               # Model Router
   │  ├─ asr/                    # Whisper 等 ASR 适配器
   │  ├─ tts/                    # GPT-SoVITS 等 TTS 适配器
   │  ├─ llm/                    # 本地或远程 LLM 适配器
   │  ├─ vision/                 # Vision 模型适配器
   │  └─ ocr/                    # Tesseract / EasyOCR 适配器
   ├─ memory/
   │  ├─ reader.py               # 记忆读取
   │  ├─ writer.py               # 记忆写入
   │  └─ relationship.py         # Relationship 规划模块
   ├─ actions/
   │  ├─ registry.py             # Action 注册
   │  ├─ validator.py            # Action 参数校验
   │  └─ dispatcher.py           # Action 执行
   ├─ state/
   │  ├─ session.py              # 会话状态
   │  └─ emotion.py              # 情绪状态
   └─ workers/
      ├─ audio.py                # 音频任务
      └─ vision.py               # Vision / OCR 任务
```

## 前端目录规划

```text
apps/desktop/
├─ main/                         # Electron 主进程
├─ preload/                      # 安全 IPC 桥接
└─ renderer/
   ├─ ui/                        # 页面和交互组件
   ├─ live2d/                    # Live2D 加载、表情和动作
   ├─ audio/                     # 录音、播放和打断
   └─ transport/                 # WebSocket 客户端
```

Renderer 负责界面和角色表现；模型调用、Memory、Action 和设备控制由后端负责。

## 前后端协议规划

协议统一放在 `shared/contracts/`，前后端不应该各自猜测消息字段。

```text
shared/
└─ contracts/
   ├─ control-message.schema.json
   ├─ action.schema.json
   └─ protocol.md
```

控制消息至少需要支持：

- 用户文本输入
- ASR 中间结果和最终结果
- Agent 回复文本
- TTS 播放状态
- 情绪和 Live2D 状态
- Action 请求和 Action 结果
- 错误、取消和超时

语音数据可以使用独立的 Voice WebSocket，避免音频流阻塞控制消息。普通控制消息使用 JSON；语音通道的具体音频格式需要在协议文档中明确。

## MVP 开发顺序

### Phase 1：基础通信

- Electron 启动
- FastAPI 启动
- Electron 与 FastAPI 建立 WebSocket
- 文本消息发送和接收

### Phase 2：最小对话闭环

```text
文本/麦克风 → ASR → LLM → TTS → Electron 播放
```

先接入一个 ASR、一个 LLM 和一个 TTS，不同时实现多个模型供应商。

### Phase 3：角色表现

- Live2D 表情
- 说话状态
- 情绪状态
- 用户打断
- 字幕显示

### Phase 4：扩展能力

- Vision
- OCR
- Video 抽帧
- Memory
- Relationship
- Action Controller
- 外部设备控制

如果后续要实现类似持续运行的虚拟角色，再增加 `World` 模块，负责时间、环境、角色状态和主动行为；不要把持续生活循环直接塞进 `Agent Core`。

## 参考项目

- [my-neuro](https://github.com/morettt/my-neuro)：参考桌面虚拟角色、Live2D、语音、视觉、长期记忆和情绪功能范围。
- [neuro-sdk](https://github.com/VedalAI/neuro-sdk)：参考 WebSocket 协议、Action 注册、Action Schema、参数校验和 Action Result。
- [yuiju](https://github.com/yixiaojiu/yuiju)：参考 `World`、`Message`、`Memory`、`Web` 的职责分离，以及持续运行角色的设计思路。

本项目只选择性借鉴这些项目的边界和协议设计，不直接复制其部署方式或全部基础设施。

## 开发原则

- Electron Renderer 不直接调用模型服务。
- Agent Core 不直接操作外部设备。
- 模型通过统一 Adapter 接入，由 Model Router 负责选择。
- Action 必须有明确的名称、描述、参数结构和执行结果。
- 长期记忆和当前会话状态分开保存。
- Vision 和 Video 任务采用抽帧或异步 Worker，避免阻塞 WebSocket。
- 尚未实现的功能在文档中标记为规划，不提前宣称完成。
