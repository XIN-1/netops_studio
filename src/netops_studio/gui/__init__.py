"""表现层（gui/）。

各功能模块 Widget，经 TabRegistry 懒加载。GUI 可 import core / app，
但 core 不得反向 import GUI（依赖方向约束）。
"""
