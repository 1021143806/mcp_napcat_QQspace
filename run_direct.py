"""
QQ Space MCP Server - 直接运行脚本
无需安装，直接运行此脚本即可启动 MCP 服务器
"""

import asyncio
import sys
from pathlib import Path

# 添加 src 目录到 Python 路径
src_path = Path(__file__).parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from qqspace_mcp.server import main

if __name__ == "__main__":
    asyncio.run(main())
