"""允许通过 python -m qqspace_mcp 启动"""

from .server import main
import asyncio

asyncio.run(main())
