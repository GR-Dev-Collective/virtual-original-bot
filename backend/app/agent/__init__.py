"""Agent 决策与流程编排。

当前 AgentCore 调用 ChatModel 生成文本，并在回复含日文假名时执行一次中文改写。
Memory、Relationship、Emotion 和 Action 目前尚未接入；TTS 生命周期由控制通道编排。
"""
