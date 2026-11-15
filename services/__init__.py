"""仓库内的独立服务包集合。

注意：本包下的子包名不得使用 ``indextts``。真实模型库
（``C:\\Users\\chen\\Documents\\deepseek-harness\\default-workspace\\index-tts\\indextts``）
必须保持可导入；若在仓库根目录放置同名包，会遮蔽真实库，导致
``from indextts.infer_v2_5 import IndexTTS2`` 失败。
"""
