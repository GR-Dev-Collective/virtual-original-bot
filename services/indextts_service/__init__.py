"""IndexTTS-2.5 语音克隆 sidecar 服务。

包名刻意使用 ``indextts_service`` 而不是 ``indextts``，避免在仓库根目录导入时
遮蔽真实的 ``indextts`` 模型库（``indextts.infer_v2_5``）。
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
