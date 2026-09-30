"""Agent 决策与流程编排。

Phase 1 只做回声，用来验证 transport → agent → transport 整条链路是通的。
接入 LLM、Memory 和 TTS 属于 Phase 2，届时替换 handle_user_text 的实现。
"""
