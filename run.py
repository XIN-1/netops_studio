"""一键启动 NetOps Studio。

用法（在仓库根目录 E:\\Code\\netops_studio 下）：

    python run.py

内部把 src/ 加入 sys.path，再以包模块方式导入 netops_studio.main，
从而让 main.py 里的相对导入（from .app import ...）正常工作，
并正确解析数据目录 src/netops_studio/data。

等价于从 src/ 目录运行：python -m netops_studio.main
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from netops_studio.main import main

if __name__ == "__main__":
    raise SystemExit(main())
