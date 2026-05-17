"""
QQ Space MCP Server
MCP server for QQ Space operations (send feeds, read feeds, like, comment, reply, AI image generation)
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


def clean_schema(schema: dict) -> dict:
    """Remove non-compliant fields from JSON Schema for Anthropic API compatibility.
    Claude API requires strict JSON Schema draft 2020-12 compliance and rejects
    $schema, title, and default fields that Pydantic model_json_schema() generates.
    """
    if not isinstance(schema, dict):
        return schema
    cleaned = {}
    for key, value in schema.items():
        if key in ("$schema", "title", "default"):
            continue
        if key == "properties" and isinstance(value, dict):
            cleaned[key] = {k: clean_schema(v) for k, v in value.items()}
        elif key == "items" and isinstance(value, dict):
            cleaned[key] = clean_schema(value)
        elif key == "additionalProperties" and isinstance(value, dict):
            cleaned[key] = clean_schema(value)
        else:
            cleaned[key] = value
    return cleaned

# ============================================================================
# Logging
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger("qqspace_mcp.server")

# ============================================================================
# Request parameter models
# ============================================================================

class SendFeedParam(BaseModel):
    content: str = Field(description="Feed text content")
    images: list[str] | None = Field(default=None, description="List of base64-encoded images (optional)")

class GetFeedsParam(BaseModel):
    target_qq: str = Field(description="Target QQ number")
    num: int = Field(default=5, description="Number of feeds to retrieve")
    filter_commented: bool = Field(default=True, description="Whether to filter out already-commented feeds")

class LikeFeedParam(BaseModel):
    fid: str = Field(description="Feed dynamic ID")
    target_qq: str = Field(description="Target QQ number")

class CommentFeedParam(BaseModel):
    fid: str = Field(description="Feed dynamic ID")
    target_qq: str = Field(description="Target QQ number")
    content: str = Field(description="Comment content")

class ReplyCommentParam(BaseModel):
    fid: str = Field(description="Feed dynamic ID")
    target_qq: str = Field(description="Target QQ number")
    target_nickname: str = Field(description="Target QQ nickname")
    content: str = Field(description="Reply content")
    comment_tid: str = Field(description="Comment ID")

class GetSendHistoryParam(BaseModel):
    num: int = Field(default=10, description="Number of history feeds to retrieve")

class RenewCookiesParam(BaseModel):
    methods: str | None = Field(default=None, description="Cookie retrieval methods (comma-separated), e.g. 'napcat,qrcode,local'")

class GenerateImageParam(BaseModel):
    prompt: str = Field(description="Image generation prompt")
    model: str | None = Field(default=None, description="AI image model (optional, uses configured model by default)")
    reference: str | None = Field(default=None, description="Reference image URL or local path (optional)")

class GetFeedsSummaryParam(BaseModel):
    target_qq: str = Field(description="Target QQ number")
    num: int = Field(default=10, description="Number of feeds to retrieve")
    filter_commented: bool = Field(default=True, description="Whether to filter out already-commented feeds")

class GetFeedDetailParam(BaseModel):
    target_qq: str = Field(description="Target QQ number")
    tid: str = Field(description="Feed dynamic ID")


# ============================================================================
# MCP Server
# ============================================================================

app = Server("qqspace-mcp")


# ============================================================================
# Tool definitions
# ============================================================================

@app.list_tools()
async def list_tools() -> list[Tool]:
    tools = [
        # QQ Space operations
        Tool(
            name="qzone_send_feed",
            description="Send a feed (post) to QQ Space with optional text and images",
            inputSchema=clean_schema(SendFeedParam.model_json_schema()),
        ),
        Tool(
            name="qzone_get_feeds",
            description="Get the feed list of a specified QQ user",
            inputSchema=clean_schema(GetFeedsParam.model_json_schema()),
        ),
        Tool(
            name="qzone_get_zone_feeds",
            description="Get the latest feeds from friends in your own QQ Space",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="qzone_like_feed",
            description="Like a specified feed",
            inputSchema=clean_schema(LikeFeedParam.model_json_schema()),
        ),
        Tool(
            name="qzone_comment_feed",
            description="Comment on a specified feed",
            inputSchema=clean_schema(CommentFeedParam.model_json_schema()),
        ),
        Tool(
            name="qzone_reply_comment",
            description="Reply to a specified comment on a feed",
            inputSchema=clean_schema(ReplyCommentParam.model_json_schema()),
        ),
        Tool(
            name="qzone_get_send_history",
            description="Get the history of feeds you have posted",
            inputSchema=clean_schema(GetSendHistoryParam.model_json_schema()),
        ),
        Tool(
            name="qzone_renew_cookies",
            description="Refresh QQ Space cookies",
            inputSchema=clean_schema(RenewCookiesParam.model_json_schema()),
        ),
        # Lite & summary tools (smaller responses, no image base64)
        Tool(
            name="qzone_get_feeds_summary",
            description="Get a lightweight summary list of feeds (tid, time, preview text, image/video/comment counts). Use this first for browsing; use qzone_get_feed_detail for full content with images.",
            inputSchema=clean_schema(GetFeedsSummaryParam.model_json_schema()),
        ),
        Tool(
            name="qzone_get_feeds_lite",
            description="Get feeds with full text and comments but image URLs instead of base64 (much smaller response). Use qzone_get_feed_detail to get actual image data for a specific feed.",
            inputSchema=clean_schema(GetFeedsParam.model_json_schema()),
        ),
        Tool(
            name="qzone_get_zone_feeds_lite",
            description="Get zone feeds with full text but image URLs instead of base64 (much smaller response).",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="qzone_get_send_history_lite",
            description="Get send history with image URLs instead of base64 (much smaller response).",
            inputSchema=clean_schema(GetSendHistoryParam.model_json_schema()),
        ),
        Tool(
            name="qzone_get_feed_detail",
            description="Get a single feed with full content including base64-encoded images. Use after browsing summaries to get image data for a specific feed.",
            inputSchema=clean_schema(GetFeedDetailParam.model_json_schema()),
        ),
    ]

    # AI image generation (optional)
    if IMAGE_ENABLED:
        tools.append(
            Tool(
                name="qzone_generate_image",
                description="Generate an image using AI (OpenAI-compatible format)",
                inputSchema=clean_schema(GenerateImageParam.model_json_schema()),
            )
        )

    return tools


# ============================================================================
# Tool implementations
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
                return [TextContent(type="text", text="Error: Unable to create QzoneAPI instance. Please refresh cookies first.")]

            # Process images
            images_bytes = []
            if params.images:
                import base64
                for img_str in params.images:
                    try:
                        images_bytes.append(base64.b64decode(img_str))
                    except Exception as e:
                        return [TextContent(type="text", text=f"Error: Failed to decode base64 image: {e}")]

            fid = await qzone.publish_emotion(content=params.content, images=images_bytes if images_bytes else None)
            if fid is None:
                return [TextContent(type="text", text="Failed to send feed")]
            return [TextContent(type="text", text=f"Feed sent successfully. Feed ID: {fid}")]

        # ---- qzone_get_feeds ----
        elif name == "qzone_get_feeds":
            params = GetFeedsParam(**arguments)
            await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, COOKIE_METHODS)
            qzone = create_qzone_api()
            if qzone is None:
                return [TextContent(type="text", text="Error: Unable to create QzoneAPI instance. Please refresh cookies first.")]

            feeds_list = await qzone.get_list(params.target_qq, params.num, params.filter_commented)
            return [TextContent(type="text", text=json.dumps(feeds_list, ensure_ascii=False, indent=2))]

        # ---- qzone_get_zone_feeds ----
        elif name == "qzone_get_zone_feeds":
            await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, COOKIE_METHODS)
            qzone = create_qzone_api()
            if qzone is None:
                return [TextContent(type="text", text="Error: Unable to create QzoneAPI instance. Please refresh cookies first.")]

            feeds_list = await qzone.get_qzone_list()
            return [TextContent(type="text", text=json.dumps(feeds_list, ensure_ascii=False, indent=2))]

        # ---- qzone_like_feed ----
        elif name == "qzone_like_feed":
            params = LikeFeedParam(**arguments)
            await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, COOKIE_METHODS)
            qzone = create_qzone_api()
            if qzone is None:
                return [TextContent(type="text", text="Error: Unable to create QzoneAPI instance. Please refresh cookies first.")]

            result = await qzone.like(params.fid, params.target_qq)
            if result:
                return [TextContent(type="text", text="Like successful")]
            return [TextContent(type="text", text="Like failed")]

        # ---- qzone_comment_feed ----
        elif name == "qzone_comment_feed":
            params = CommentFeedParam(**arguments)
            await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, COOKIE_METHODS)
            qzone = create_qzone_api()
            if qzone is None:
                return [TextContent(type="text", text="Error: Unable to create QzoneAPI instance. Please refresh cookies first.")]

            result = await qzone.comment(params.fid, params.target_qq, params.content)
            if result:
                return [TextContent(type="text", text="Comment successful")]
            return [TextContent(type="text", text="Comment failed")]

        # ---- qzone_reply_comment ----
        elif name == "qzone_reply_comment":
            params = ReplyCommentParam(**arguments)
            await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, COOKIE_METHODS)
            qzone = create_qzone_api()
            if qzone is None:
                return [TextContent(type="text", text="Error: Unable to create QzoneAPI instance. Please refresh cookies first.")]

            result = await qzone.reply(params.fid, params.target_qq, params.target_nickname, params.content, params.comment_tid)
            if result:
                return [TextContent(type="text", text="Reply successful")]
            return [TextContent(type="text", text="Reply failed")]

        # ---- qzone_get_send_history ----
        elif name == "qzone_get_send_history":
            params = GetSendHistoryParam(**arguments)
            await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, COOKIE_METHODS)
            qzone = create_qzone_api()
            if qzone is None:
                return [TextContent(type="text", text="Error: Unable to create QzoneAPI instance. Please refresh cookies first.")]

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
                return [TextContent(type="text", text="Cookies refreshed successfully")]
            return [TextContent(type="text", text="Cookie refresh failed (may have been refreshed within 1 hour, or all methods failed)")]

        # ---- qzone_get_feeds_summary ----
        elif name == "qzone_get_feeds_summary":
            params = GetFeedsSummaryParam(**arguments)
            await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, COOKIE_METHODS)
            qzone = create_qzone_api()
            if qzone is None:
                return [TextContent(type="text", text="Error: Unable to create QzoneAPI instance. Please refresh cookies first.")]

            summary = await qzone.get_feeds_summary(params.target_qq, params.num, params.filter_commented)
            return [TextContent(type="text", text=json.dumps(summary, ensure_ascii=False, indent=2))]

        # ---- qzone_get_feeds_lite ----
        elif name == "qzone_get_feeds_lite":
            params = GetFeedsParam(**arguments)
            await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, COOKIE_METHODS)
            qzone = create_qzone_api()
            if qzone is None:
                return [TextContent(type="text", text="Error: Unable to create QzoneAPI instance. Please refresh cookies first.")]

            feeds_list = await qzone.get_list_lite(params.target_qq, params.num, params.filter_commented)
            return [TextContent(type="text", text=json.dumps(feeds_list, ensure_ascii=False, indent=2))]

        # ---- qzone_get_zone_feeds_lite ----
        elif name == "qzone_get_zone_feeds_lite":
            await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, COOKIE_METHODS)
            qzone = create_qzone_api()
            if qzone is None:
                return [TextContent(type="text", text="Error: Unable to create QzoneAPI instance. Please refresh cookies first.")]

            feeds_list = await qzone.get_qzone_list_lite()
            return [TextContent(type="text", text=json.dumps(feeds_list, ensure_ascii=False, indent=2))]

        # ---- qzone_get_send_history_lite ----
        elif name == "qzone_get_send_history_lite":
            params = GetSendHistoryParam(**arguments)
            await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, COOKIE_METHODS)
            qzone = create_qzone_api()
            if qzone is None:
                return [TextContent(type="text", text="Error: Unable to create QzoneAPI instance. Please refresh cookies first.")]

            feeds_list = await qzone.get_list_lite(target_qq=str(qzone.uin), num=params.num)
            history = "==================="
            for feed in feeds_list:
                if not feed.get("rt_con", ""):
                    history += f"""
时间：'{feed.get("created_time", "")}'。
说说内容：'{feed.get("content", "")}'
图片URL：'{feed.get("images", [])}'
===================
"""
                else:
                    history += f"""
时间: '{feed.get("created_time", "")}'。
转发了一条说说，内容为: '{feed.get("rt_con", "")}'
图片URL: '{feed.get("images", [])}'
对该说说的评论为: '{feed.get("content", "")}'
===================
"""
            return [TextContent(type="text", text=history)]

        # ---- qzone_get_feed_detail ----
        elif name == "qzone_get_feed_detail":
            params = GetFeedDetailParam(**arguments)
            await renew_cookies(HTTP_HOST, str(HTTP_PORT), NAPCAT_TOKEN, COOKIE_METHODS)
            qzone = create_qzone_api()
            if qzone is None:
                return [TextContent(type="text", text="Error: Unable to create QzoneAPI instance. Please refresh cookies first.")]

            detail = await qzone.get_feed_detail(params.target_qq, params.tid)
            if detail is None:
                return [TextContent(type="text", text=f"Feed not found: tid={params.tid}")]
            return [TextContent(type="text", text=json.dumps(detail, ensure_ascii=False, indent=2))]

        # ---- qzone_generate_image ----
        elif name == "qzone_generate_image":
            if not IMAGE_ENABLED:
                return [TextContent(type="text", text="AI image generation is not enabled. Set IMAGE_ENABLED=true in config.")]

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
                logger.info(f"Generating image with model {model}: {params.prompt}")
                response = client.images.generate(**body)

                if response is None or not response.data:
                    return [TextContent(type="text", text="Image generation failed: no valid response received")]

                img = response.data[0]
                if img.url:
                    logger.info("Downloading image...")
                    r = req.get(img.url, timeout=30)
                    r.raise_for_status()
                    img_base64 = b64.b64encode(r.content).decode('utf-8')
                    return [TextContent(type="text", text=f"Image generated successfully (base64):\n{img_base64}")]
                elif img.b64_json:
                    return [TextContent(type="text", text=f"Image generated successfully (base64):\n{img.b64_json}")]
                else:
                    return [TextContent(type="text", text="Image data is empty")]

            except ImportError:
                return [TextContent(type="text", text="AI image generation requires openai and requests packages. Run: pip install openai requests")]
            except Exception as e:
                return [TextContent(type="text", text=f"Image generation failed: {str(e)}")]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        error_msg = f"Tool call failed [{name}]: {str(e)}"
        logger.error(error_msg)
        return [TextContent(type="text", text=error_msg)]


async def main():
    """Start MCP server"""
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
