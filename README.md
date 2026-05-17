# QQ Space MCP Server

封装 QQ 空间操作的 MCP 服务器。支持发说说、读说说、点赞、评论、回复等操作。

> 基于 [Maizone](https://github.com/internetsb/Maizone) 插件改造，移除 MaiBot SDK 依赖，作为独立 MCP Server 运行。

## 功能特性

- 📝 **发说说**：发送文本和图片到 QQ 空间
- 📖 **读说说**：获取指定 QQ 号的好友说说列表
- 🌐 **空间动态**：获取自己空间下好友的最新动态
- ❤️ **点赞**：点赞指定说说
- 💬 **评论**：评论指定说说
- ↩️ **回复**：回复指定评论
- 📜 **说说历史**：获取自己发过的说说历史
- 🔑 **Cookie 管理**：支持 Napcat HTTP、扫码登录、本地文件多种方式
- 🎨 **AI 生图**：可选功能，使用 OpenAI 兼容 API 生成图片

## 安装

```bash
git clone <repo_url> mcp_QQspace
cd mcp_QQspace
pip install -e .
```

### 可选依赖

```bash
# AI 生图功能
pip install openai requests
```

## 配置

### 方式一：TOML 配置文件

```bash
cp config/template/config.toml config/env.toml
# 编辑 config/env.toml
```

### 方式二：环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `QZONE_HTTP_HOST` | Napcat HTTP 服务地址 | `127.0.0.1` |
| `QZONE_HTTP_PORT` | Napcat HTTP 服务端口 | `9999` |
| `QZONE_NAPCAT_TOKEN` | Napcat 访问令牌 | 空 |
| `QZONE_COOKIE_METHODS` | Cookie 获取方式（逗号分隔） | `adapter,napcat,qrcode,local` |
| `QZONE_IMAGE_ENABLED` | 是否启用 AI 生图 | `false` |
| `QZONE_IMAGE_BASE_URL` | AI 生图服务地址 | 火山引擎 |
| `QZONE_IMAGE_MODEL` | AI 生图模型 | `doubao-seedream-5-0-260128` |
| `QZONE_IMAGE_API_KEY` | AI 生图 API Key | 空 |

## MCP 客户端配置

在 MCP 客户端配置文件中添加：

```json
{
  "mcpServers": {
    "qqspace-mcp": {
      "command": "python",
      "args": ["path/to/mcp_QQspace/run_direct.py"],
      "env": {
        "QZONE_HTTP_HOST": "127.0.0.1",
        "QZONE_HTTP_PORT": "9999",
        "QZONE_NAPCAT_TOKEN": "your_token_here"
      }
    }
  }
}
```

## 可用工具（14 个）

### QQ 空间操作（13 个）
| 工具名 | 描述 |
|--------|------|
| `qzone_send_feed` | 发送说说到 QQ 空间 |
| `qzone_get_feeds` | 获取指定 QQ 号的好友说说列表（含图片 base64，数据量大） |
| `qzone_get_feeds_summary` 🆕 | 获取说说摘要列表（tid/时间/内容预览/图片数/评论数，超精简） |
| `qzone_get_feeds_lite` 🆕 | 获取说说列表（完整文字+评论，图片仅 URL，数据量小） |
| `qzone_get_zone_feeds` | 获取自己空间下好友的最新动态（含图片 base64） |
| `qzone_get_zone_feeds_lite` 🆕 | 获取空间动态（完整文字，图片仅 URL，数据量小） |
| `qzone_get_feed_detail` 🆕 | 获取单条说说的完整数据（含图片 base64），按 tid 查询 |
| `qzone_like_feed` | 点赞指定说说 |
| `qzone_comment_feed` | 评论指定说说 |
| `qzone_reply_comment` | 回复指定评论 |
| `qzone_get_send_history` | 获取自己发过的说说历史（含图片 base64） |
| `qzone_get_send_history_lite` 🆕 | 获取说说历史（图片仅 URL，数据量小） |
| `qzone_renew_cookies` | 刷新 QQ 空间 Cookie |

### AI 生图（1 个，可选）
| 工具名 | 描述 |
|--------|------|
| `qzone_generate_image` | 使用 AI 生成图片 |

### 推荐使用方式

为减少返回数据量，建议按以下分层方式使用：

1. **快速浏览** → 先用 `qzone_get_feeds_summary` 获取摘要列表
2. **阅读内容** → 用 `qzone_get_feeds_lite` / `qzone_get_zone_feeds_lite` 获取完整文字
3. **查看图片** → 用 `qzone_get_feed_detail` 按 tid 获取单条含图片的完整数据

## Cookie 获取方式

支持以下 Cookie 获取方式（按配置顺序尝试）：

1. **adapter** - 通过 Napcat Adapter API 获取
2. **napcat** - 通过 Napcat HTTP 服务获取
3. **qrcode** - 生成二维码，手机 QQ 扫码登录
4. **local** - 读取本地 `cookies.json` 文件

## NapCat 配置

确保 NapCat 的 OneBot11 配置中启用了 HTTP 服务器：

```json
{
  "network": {
    "httpServers": [{
      "enable": true,
      "name": "qqspace mcp",
      "host": "127.0.0.1",
      "port": 9999,
      "enableCors": true,
      "enableWebsocket": true,
      "messagePostFormat": "array",
      "token": "your_token_here",
      "debug": false
    }]
  }
}
```

## 项目结构

```
mcp_QQspace/
├── pyproject.toml          # 项目元数据和依赖
├── run_direct.py           # 直接运行入口
├── start.sh                # 启动脚本
├── README.md               # 项目文档
├── mcp_settings.json       # MCP 客户端配置示例
├── .gitignore
├── config/
│   ├── env.toml            # 启用的配置文件（需自行创建）
│   └── template/
│       └── config.toml     # 配置模板
├── src/
│   └── qqspace_mcp/
│       ├── __init__.py
│       ├── __main__.py
│       ├── server.py       # MCP Server 主入口
│       ├── config.py       # 配置模块
│       ├── qzone_api.py    # QQ 空间 API
│       └── cookie.py       # Cookie 管理
└── test/
    └── test_mcp.py         # 测试脚本
```

## 技术细节

- 基于 MCP (Model Context Protocol) 标准
- 使用 `httpx` 异步 HTTP 客户端
- 使用 Pydantic 进行参数验证
- 支持 TOML 配置文件 + 环境变量覆盖
- Cookie 自动管理，支持多种获取方式

## 许可证

MIT

## 鸣谢

- [Maizone](https://github.com/internetsb/Maizone) - 原始 QQ 空间插件
- [qzone-toolkit](https://github.com/gfhdhytghd/qzone-toolkit) - 部分代码来源
- [MaiBot](https://github.com/MaiM-with-u/MaiBot) - 原始机器人框架
