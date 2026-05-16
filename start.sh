#!/bin/bash
# QQ Space MCP Server 启动脚本
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 检查 Python 版本
PYTHON=$(which python3 || which python)
echo "使用 Python: $PYTHON"
$PYTHON --version

# 检查依赖
echo "检查依赖..."
$PYTHON -c "import mcp" 2>/dev/null || {
    echo "mcp 未安装，正在安装..."
    pip install mcp httpx pydantic bs4 json5
}

# 检查配置文件
if [ ! -f "config/env.toml" ]; then
    echo "配置文件 config/env.toml 不存在，使用模板配置"
    if [ -f "config/template/config.toml" ]; then
        cp config/template/config.toml config/env.toml
        echo "已从模板创建 config/env.toml，请修改配置后重新启动"
    fi
fi

# 启动 MCP 服务器
echo "启动 QQ Space MCP Server..."
exec $PYTHON run_direct.py
