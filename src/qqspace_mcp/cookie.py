"""
QQ Space MCP Server - Cookie 管理模块
支持 Napcat HTTP、扫码登录、本地文件三种方式获取 Cookie
改造自 Maizone 插件，移除 MaiBot SDK 依赖
"""

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path

import httpx

logger = logging.getLogger("qqspace_mcp.cookie")

# ============================================================================
# 路径常量
# ============================================================================

_PLUGIN_DIR = Path(__file__).parent.parent.parent
COOKIE_PATH = str(_PLUGIN_DIR / "cookies.json")
QRCODE_PATH = str(_PLUGIN_DIR / "qrcode.png")

# ============================================================================
# QQ 空间二维码登录相关 URL
# ============================================================================

_QRCODE_URL = "https://ssl.ptlogin2.qq.com/ptqrshow?appid=549000912&e=2&l=M&s=3&d=72&v=4&t=0.31232733520361844&daid=5&pt_3rd_aid=0"
_LOGIN_CHECK_URL = "https://xui.ptlogin2.qq.com/ssl/ptqrlogin?u1=https://qzs.qq.com/qzone/v5/loginsucc.html?para=izone&ptqrtoken={}&ptredirect=0&h=1&t=1&g=1&from_ui=1&ptlang=2052&action=0-0-1656992258324&js_ver=22070111&js_type=1&login_sig=&pt_uistyle=40&aid=549000912&daid=5&has_onekey=1&&o1vId=1e61428d61cb5015701ad73d5fb59f73"
_CHECK_SIG_URL = "https://ptlogin2.qzone.qq.com/check_sig?pttype=1&uin={}&service=ptqrlogin&nodirect=1&ptsigx={}&s_url=https://qzs.qq.com/qzone/v5/loginsucc.html?para=izone&f_url=&ptlang=2052&ptredirect=100&aid=549000912&daid=5&j_later=0&low_login_hour=0&regmaster=0&pt_login_type=3&pt_aid=0&pt_aaid=16&pt_light=0&pt_3rd_aid=0"

# 内存中的上次 cookie 更新时间
_last_cookie_update_time = 0

# 支持的 cookie 更新方法
COOKIE_METHODS = ["adapter", "napcat", "qrcode", "local"]


# ============================================================================
# 工具函数
# ============================================================================

def read_local_cookies() -> dict | None:
    """读取本地 cookie 文件"""
    if not os.path.exists(COOKIE_PATH):
        logger.error(f"未找到本地 cookie 文件: {COOKIE_PATH}")
        return None
    try:
        with open(COOKIE_PATH, "r", encoding="utf-8") as f:
            cookie_dict = json.load(f)
        logger.info("读取本地 cookie 文件成功")
        return cookie_dict
    except Exception as e:
        logger.error(f"读取本地 cookie 文件失败: {str(e)}")
        return None


def should_skip_qr_login(qrcode: bool = False) -> bool:
    """检查是否应该跳过二维码登录（一小时内跳过，若是扫码登录则放宽至20小时内）"""
    global _last_cookie_update_time
    if _last_cookie_update_time == 0:
        return False

    current_time = time.time()
    if qrcode:
        return (current_time - _last_cookie_update_time) < 20 * 3600
    return (current_time - _last_cookie_update_time) < 3600


def update_last_cookie_update_time():
    """更新上次 cookie 更新时间"""
    global _last_cookie_update_time
    _last_cookie_update_time = time.time()


def parse_cookie_string(cookie_str: str) -> dict:
    """将 cookie 字符串解析为字典"""
    return {pair.split("=", 1)[0]: pair.split("=", 1)[1] for pair in cookie_str.split("; ")}


def getptqrtoken(qrsig):
    """协议特定计算算法"""
    e = 0
    for i in range(1, len(qrsig) + 1):
        e += (e << 5) + ord(qrsig[i - 1])
    return str(2147483647 & e)


# ============================================================================
# 获取 Cookie 函数
# ============================================================================

async def fetch_cookies_by_napcat(
    host: str,
    domain: str = "user.qzone.qq.com",
    port: str = "9999",
    napcat_token: str = "",
    max_retries: int = 1,
    retry_delay: int = 10,
) -> dict | None:
    """通过 Napcat HTTP 服务器获取 cookie 字典"""
    url = f"http://{host}:{port}/get_cookies"

    for attempt in range(max_retries):
        try:
            headers = {"Content-Type": "application/json"}
            if napcat_token:
                headers["Authorization"] = f"Bearer {napcat_token}"

            payload = {"domain": domain}

            async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()

                if resp.status_code != 200:
                    error_msg = f"Napcat 服务返回错误状态码: {resp.status_code}"
                    if resp.status_code == 403:
                        error_msg += " (Token 验证失败)"
                    logger.error(error_msg)
                    continue

                data = resp.json()
                if data.get("status") != "ok" or "cookies" not in data.get("data", {}):
                    logger.error(f"获取 cookie 失败: {data}")
                    continue
                cookie_data = data["data"]
                cookie_str = cookie_data["cookies"]
                parsed_cookies = parse_cookie_string(cookie_str)
                return parsed_cookies

        except httpx.RequestError as e:
            if attempt < max_retries - 1:
                logger.warning(f"无法连接到 Napcat 服务(尝试 {attempt + 1}/{max_retries}): {url}，错误: {str(e)}")
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
                continue
            logger.error(f"无法连接到 Napcat 服务(最终尝试): {url}，错误: {str(e)}")
        except Exception as e:
            logger.error(f"获取 cookie 异常: {str(e)}")

    logger.error(f"无法连接到 Napcat 服务: 超过最大重试次数({max_retries})")
    return None


async def fetch_cookies_by_qrcode(max_timeout_times: int = 3) -> dict | None:
    """在插件目录下生成 qrcode.png，通过二维码登录获取 cookie 字典，成功登录后删除二维码图片"""
    for i in range(max_timeout_times):
        async with httpx.AsyncClient() as client:
            req = await client.get(_QRCODE_URL)
            qrsig = ''

            set_cookies_set = req.headers.get('Set-Cookie', '').split(";")
            for set_cookies in set_cookies_set:
                if set_cookies.startswith("qrsig"):
                    qrsig = set_cookies.split("=")[1]
                    break
            if qrsig == '':
                logger.error("qrsig is empty")
                continue

            ptqrtoken = getptqrtoken(qrsig)

            with open(QRCODE_PATH, "wb") as f:
                f.write(req.content)
            logger.info(f"二维码已保存于 {QRCODE_PATH}，请两分钟内使用手机 QQ 扫描登录")

            for _ in range(60):
                await asyncio.sleep(2)
                req = await client.get(_LOGIN_CHECK_URL.format(ptqrtoken), cookies={"qrsig": qrsig})
                if req.text.find("二维码已失效") != -1:
                    logger.info("二维码已失效，重新获取...")
                    break
                if req.text.find("登录成功") != -1:
                    response_header_dict = req.headers
                    url = eval(req.text.replace("ptuiCB", ""))[2]

                    m = re.findall(r"ptsigx=[A-z \d]*&", url)
                    ptsigx = m[0].replace("ptsigx=", "").replace("&", "")

                    m = re.findall(r"uin=[\d]*&", url)
                    uin = m[0].replace("uin=", "").replace("&", "")

                    res = await client.get(
                        _CHECK_SIG_URL.format(uin, ptsigx),
                        cookies={"qrsig": qrsig},
                        headers={'Cookie': response_header_dict.get('Set-Cookie', '')},
                    )

                    final_cookie = res.headers.get('Set-Cookie', '')
                    final_cookie_dict = {}
                    for set_cookie in final_cookie.split(";, "):
                        for cookie in set_cookie.split(";"):
                            spt = cookie.split("=")
                            if len(spt) == 2 and final_cookie_dict.get(spt[0]) is None:
                                final_cookie_dict[spt[0]] = spt[1]

                    if os.path.exists(QRCODE_PATH):
                        os.remove(QRCODE_PATH)

                    update_last_cookie_update_time()
                    return final_cookie_dict
                logger.debug("等待扫码登录...")
    logger.error(f"{max_timeout_times}次尝试失败")
    return None


async def renew_cookies(
    host: str = "127.0.0.1",
    port: str = "9999",
    napcat_token: str = "",
    methods: list[str] | None = None,
    fallback_to_local: bool = True,
) -> bool:
    """
    尝试更新 cookie 并保存到本地文件

    参数:
        host: Napcat 服务主机地址
        port: Napcat 服务端口
        napcat_token: Napcat 认证令牌
        methods: 更新方法列表，按顺序尝试，支持: "adapter", "napcat", "qrcode", "local"
        fallback_to_local: 当所有方法都失败时是否回退到本地 cookie 文件
    返回:
        bool: 是否成功更新 cookie
    """
    # 1小时内跳过更新 cookie
    if should_skip_qr_login():
        logger.info("上次 cookie 更新时间在1小时内，跳过更新")
        return False

    if methods is None:
        methods = ["napcat", "qrcode", "local"]

    valid_methods = [method for method in methods if method in COOKIE_METHODS]
    if not valid_methods:
        logger.warning("没有有效的 cookie 更新方法，使用默认方法")
        valid_methods = ["napcat", "qrcode", "local"]

    logger.info(f"使用 cookie 更新方法: {valid_methods}")

    cookie_dict = None
    last_error = None

    for method in valid_methods:
        try:
            if method == "adapter":
                logger.info("尝试通过 Napcat Adapter 获取 cookie...")
                cookie_dict = await fetch_cookies_by_napcat(host, "user.qzone.qq.com", port, napcat_token)
                if cookie_dict:
                    logger.info("Napcat Adapter 获取 cookie 成功")
                    break
                else:
                    logger.info("Napcat Adapter 获取 cookie 失败，尝试下一个方法")
                    continue

            if method == "napcat":
                logger.info("尝试通过 Napcat 获取 cookie...")
                cookie_dict = await fetch_cookies_by_napcat(host, "user.qzone.qq.com", port, napcat_token)
                if cookie_dict:
                    logger.info("Napcat 获取 cookie 成功")
                    break
                else:
                    logger.info("Napcat 获取 cookie 失败，尝试下一个方法")
                    continue

            elif method == "qrcode":
                if should_skip_qr_login(qrcode=True):
                    logger.info("上次扫码登录在20小时内，跳过二维码登录")
                    continue

                logger.info("尝试通过二维码登录获取 cookie...")
                cookie_dict = await fetch_cookies_by_qrcode()
                if cookie_dict:
                    logger.info("二维码登录成功")
                    break
                else:
                    logger.info("二维码登录失败，尝试下一个方法")
                    continue

            elif method == "local":
                logger.info("尝试读取本地 cookie 文件...")
                cookie_dict = read_local_cookies()
                if cookie_dict:
                    logger.info("读取本地 cookie 文件成功")
                    break
                else:
                    logger.info("读取本地 cookie 文件失败，尝试下一个方法")
                    continue

        except Exception as e:
            logger.error(f"{method} 方法获取 cookie 失败: {str(e)}")
            last_error = e
            continue

    if cookie_dict is None and fallback_to_local and "local" not in valid_methods:
        try:
            logger.info("所有配置方法都失败，尝试读取本地 cookie 文件作为回退")
            cookie_dict = read_local_cookies()
            if cookie_dict:
                logger.info("本地文件回退成功")
        except Exception as e:
            logger.error(f"回退到本地 cookie 文件失败: {str(e)}")

    if cookie_dict is None or not cookie_dict:
        if last_error:
            logger.error(f"所有 cookie 获取方法都失败，最后错误: {str(last_error)}")
        else:
            logger.error("所有 cookie 获取方法都失败")
        return False

    try:
        directory = os.path.dirname(COOKIE_PATH)
        if not os.path.exists(directory):
            os.makedirs(directory)

        with open(COOKIE_PATH, "w", encoding="utf-8") as f:
            json.dump(cookie_dict, f, indent=4, ensure_ascii=False)
        logger.info(f"[OK] cookies 已保存至: {COOKIE_PATH}")
        update_last_cookie_update_time()

    except Exception as e:
        logger.error(f"保存 cookie 文件失败: {str(e)}")
        return False

    return True
