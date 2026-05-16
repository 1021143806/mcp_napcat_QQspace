"""
QQ Space MCP Server
封装 QQ 空间操作的 MCP 服务器（发说说、读说说、点赞、评论、回复、AI 生图）
"""

import asyncio
import json
import logging
import os
from typing import Any

from mcp.server import Server
from mcp.types import Tool, TextContent
from pydantic import BaseModel, Field

from .config import (
    HTTP_HOST,
    HTTP_PORT,
    NAPCAT_TOKEN,
    COOKIE_METHODS,
    IMAGE_ENABLED,
    IMAGE_BASE_URL,
    IMAGE_MODEL,
    IMAGE_API_KEY,
    IMAGE_ENABLE_REFERENCE,
    IMAGE_REFERENCE,
    print_config,
)
from .cookie import renew_cookies
from .qzone_api import create_qzone_api

# ============================================================================
# 日志
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger("qqspace_mcp.server")

# ============================================================================
# 请求参数模型
# ============================================================================

class SendFeedParam(BaseModel):
    content: str = Field(description="说说文本内容")
    images: list[str] | None = Field(default=None, description="图片 base64 列表（可选）")

class GetFeedsParam(BaseModel):
    target_qq: str = Field(description="目标 QQ 号")
    num: int = Field(default=5, description="获取数量")
    filter_commented: bool = Field(default=True, description="是否过滤已评论过的说说")

class LikeFeedParam(BaseModel):
    fid: str = Field(description="说说动态 ID")
    target_qq: str = Field(description="目标 QQ 号")

class CommentFeedParam(BaseModel):
    fid: str = Field(description="说说动态 ID")
    target_qq: str = Field(description="目标 QQ 号")
    content: str = Field(description="评论内容")

class ReplyCommentParam(BaseModel):
    fid: str = Field(description="说说动态 ID")
    target_qq: str = Field(description="目标 QQ 号")
    target_nickname: str = Field(description="目标 QQ 昵称")
    content: str = Field(description="回复内容")
    comment_tid: str = Field(description="评论 ID")

class GetSendHistoryParam(BaseModel):
    num: int = Field(default=10, description="获取数量")

class RenewCookiesParam(BaseModel):
    methods: str | None = Field(default=None, description="Cookie 获取方式（逗号分隔），如 'napcat,qrcode,local'")

class GenerateImageParam(BaseModel):
    prompt: str = Field(description="图片生成提示词")
    model: str | None = Field(default=None, description="AI 生图模型（可选，默认使用配置中的模型）")
    reference: str | None = Field(default=None, description="参考图 URL 或本地路径（可选）")


# ============================================================================
# MCP 服务器
# ============================================================================

app = Server("qqspace-mcp")


# ============================================================================
# 工具定义
# ============================================================================

@app.list_tools()
async def list_tools() -> list[Tool]:
    tools = [
        # QQ 空间操作
        Tool(
            name="qzone_send_feed",
            description="发送说说到 QQ 空间（支持文本和图片）",
            inputSchema=SendFeedParam.model_json_schema(),
        ),
        Tool(
            name="qzone_get_feeds",
            description="获取指定 QQ 号的好友说说列表",
            inputSchema=GetFeedsParam.model_json_schema(),
        ),
        Tool(
            name="qzone_get_zone_feeds",
            description="获取自己 QQ 空间下好友的最新动态",
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        Tool(
            name="qzone_like_feed",
            description="点赞指定说说",
            inputSchema=LikeFeedParam.model_json_schema(),
        ),
        Tool(
            name="qzone_comment_feed",
            description="评论指定说说",
            inputSchema=CommentFeedParam.model_json_schema(),
        ),
        Tool(
            name="qzone_reply_comment",
            description="回复指定评论",
            inputSchema=ReplyCommentParam.model_json_schema(),
        ),
        Tool(
            name="qzone_get_send_history",
            description="获取自己发过的说说历史",
            inputSchema=GetSendHistoryParam.model_json_schema(),
        ),
        Tool(
            name="qzone_renew_cookies",
            description="刷新 QQ 空间 Cookie",
            inputSchema=RenewCookiesParam.model_json_schema(),
        ),
    ]

    # AI 生图（可选）
    if IMAGE_ENABLED:
        tools.append(
            Tool(
                name="qzone_generate_image",
                description="使用 AI 生成图片（OpenAI 兼容格式）",
                inputSchema=GenerateImageParam.model_json_schema(),
            )
        )

    return tools


# ============================================================================
# 工具实现
# ============================================================================

@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        # ---- qzone_send_feed ----
        if name == "qzone_send_feed":
            params = SendFeedParam(**arguments)
            await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, COOKIE_METHODS)
            qzone = create_qzone_api()
            if qzone is None:
                return [TextContent(type="text", text="错误: 无法创建 QzoneAPI 实例，请先刷新 Cookie")]

            # 处理图片
            images_bytes = []
            if params.images:
                import base64
                for img_str in params.images:
                    try:
                        images_bytes.append(base64.b64decode(img_str))
                    except Exception as e:
                        return [TextContent(type="text", text=f"错误: 图片 base64 解码失败: {e}")]

            fid = await qzone.publish_emotion(content=params.content, images=images_bytes if images_bytes else None)
            if fid is None:
                return [TextContent(type="text", text="发送说说失败")]
            return [TextContent(type="text", text=f"说说发送成功，动态ID：{fid}")]

        # ---- qzone_get_feeds ----
        elif name == "qzone_get_feeds":
            params = GetFeedsParam(**arguments)
            await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, COOKIE_METHODS)
            qzone = create_qzone_api()
            if qzone is None:
                return [TextContent(type="text", text="错误: 无法创建 QzoneAPI 实例，请先刷新 Cookie")]

            feeds_list = await qzone.get_list(params.target_qq, params.num, params.filter_commented)
            return [TextContent(type="text", text=json.dumps(feeds_list, ensure_ascii=False, indent=2))]

        # ---- qzone_get_zone_feeds ----
        elif name == "qzone_get_zone_feeds":
            await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, COOKIE_METHODS)
            qzone = create_qzone_api()
            if qzone is None:
                return [TextContent(type="text", text="错误: 无法创建 QzoneAPI 实例，请先刷新 Cookie")]

            feeds_list = await qzone.get_qzone_list()
            return [TextContent(type="text", text=json.dumps(feeds_list, ensure_ascii=False, indent=2))]

        # ---- qzone_like_feed ----
        elif name == "qzone_like_feed":
            params = LikeFeedParam(**arguments)
            await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, COOKIE_METHODS)
            qzone = create_qzone_api()
            if qzone is None:
                return [TextContent(type="text", text="错误: 无法创建 QzoneAPI 实例，请先刷新 Cookie")]

            result = await qzone.like(params.fid, params.target_qq)
            if result:
                return [TextContent(type="text", text="点赞成功")]
            return [TextContent(type="text", text="点赞失败")]

        # ---- qzone_comment_feed ----
        elif name == "qzone_comment_feed":
            params = CommentFeedParam(**arguments)
            await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, COOKIE_METHODS)
            qzone = create_qzone_api()
            if qzone is None:
                return [TextContent(type="text", text="错误: 无法创建 QzoneAPI 实例，请先刷新 Cookie")]

            result = await qzone.comment(params.fid, params.target_qq, params.content)
            if result:
                return [TextContent(type="text", text="评论成功")]
            return [TextContent(type="text", text="评论失败")]

        # ---- qzone_reply_comment ----
        elif name == "qzone_reply_comment":
            params = ReplyCommentParam(**arguments)
            await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, COOKIE_METHODS)
            qzone = create_qzone_api()
            if qzone is None:
                return [TextContent(type="text", text="错误: 无法创建 QzoneAPI 实例，请先刷新 Cookie")]

            result = await qzone.reply(params.fid, params.target_qq, params.target_nickname, params.content, params.comment_tid)
            if result:
                return [TextContent(type="text", text="回复成功")]
            return [TextContent(type="text", text="回复失败")]

        # ---- qzone_get_send_history ----
        elif name == "qzone_get_send_history":
            params = GetSendHistoryParam(**arguments)
            await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, COOKIE_METHODS)
            qzone = create_qzone_api()
            if qzone is None:
                return [TextContent(type="text", text="错误: 无法创建 QzoneAPI 实例，请先刷新 Cookie")]

            history = await qzone.get_send_history(params.num)
            return [TextContent(type="text", text=history)]

        # ---- qzone_renew_cookies ----
        elif name == "qzone_renew_cookies":
            params = RenewCookiesParam(**arguments)
            methods = None
            if params.methods:
                methods = [m.strip() for m in params.methods.split(",") if m.strip()]

            result = await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, methods or COOKIE_METHODS)
            if result:
                return [TextContent(type="text", text="Cookie 刷新成功")]
            return [TextContent(type="text", text="Cookie 刷新失败（可能在1小时内已刷新过，或所有方法均失败）")]

        # ---- qzone_generate_image ----
        elif name == "qzone_generate_image":
            if not IMAGE_ENABLED:
                return [TextContent(type="text", text="AI 生图功能未启用，请在配置中设置 IMAGE_ENABLED=true")]

            params = GenerateImageParam(**arguments)
            try:
                from openai import OpenAI
                import base64 as b64
                import requests as req
                from pathlib import Path as P

                model = params.model or IMAGE_MODEL
                reference = params.reference or (IMAGE_REFERENCE if IMAGE_ENABLE_REFERENCE else None)

                body = {
                    "model": model,
                    "prompt": params.prompt,
                    "n": 1,
                }

                if reference:
                    if reference.startswith("http://") or reference.startswith("https://"):
                        body["extra_body"] = {"image": reference}
                    else:
                        path = P(reference)
                        with open(str(path.absolute()), "rb") as f:
                            img_data = f.read()
                        fmt = path.suffix[1:].lower() if path.suffix else "png"
                        encoded = b64.b64encode(img_data).decode('utf-8')
                        body["extra_body"] = {"image": f"data:image/{fmt};base64,{encoded}"}

                client = OpenAI(base_url=IMAGE_BASE_URL, api_key=IMAGE_API_KEY)
                logger.info(f"正在使用模型 {model} 生成图片: {params.prompt}")
                response = client.images.generate(**body)

                if response is None or not response.data:
                    return [TextContent(type="text", text="图片生成失败，未收到有效响应")]

                img = response.data[0]
                if img.url:
                    logger.info("下载图片中...")
                    r = req.get(img.url, timeout=30)
                    r.raise_for_status()
                    img_base64 = b64.b64encode(r.content).decode('utf-8')
                    return [TextContent(type="text", text=f"图片生成成功 (base64):\n{img_base64}")]
                elif img.b64_json:
                    return [TextContent(type="text", text=f"图片生成成功 (base64):\n{img.b64_json}")]
                else:
                    return [TextContent(type="text", text="图片数据为空")]

            except ImportError:
                return [TextContent(type="text", text="AI 生图功能需要安装 openai 和 requests 依赖。请运行: pip install openai requests")]
            except Exception as e:
                return [TextContent(type="text", text=f"图片生成失败: {str(e)}")]

        else:
            return [TextContent(type="text", text=f"未知工具: {name}")]

    except Exception as e:
        error_msg = f"工具调用失败 [{name}]: {str(e)}"
        logger.error(error_msg)
        return [TextContent(type="text", text=error_msg)]


async def main():
    """启动 MCP 服务器"""
    from mcp.server.stdio import stdio_server

    print("=" * 60)
    print("QQ Space MCP Server v0.1.0")
    print("=" * 60)
    print_config()
    print("=" * 60)

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
