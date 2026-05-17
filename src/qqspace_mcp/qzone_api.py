"""
QQ Space MCP Server - QQ 空间 API 模块
封装 QQ 空间底层操作：发说说、点赞、评论、回复、获取列表等
改造自 Maizone 插件，移除 MaiBot SDK 依赖
"""

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import bs4
import httpx
import json5

logger = logging.getLogger("qqspace_mcp.qzone_api")

# ============================================================================
# 路径常量
# ============================================================================

_PLUGIN_DIR = Path(__file__).parent.parent.parent
COOKIE_PATH = str(_PLUGIN_DIR / "cookies.json")


# ============================================================================
# 辅助函数
# ============================================================================

def generate_gtk(skey: str) -> str:
    """特定协议算法，生成 QQ 空间的 gtk 值"""
    hash_val = 5381
    for i in range(len(skey)):
        hash_val += (hash_val << 5) + ord(skey[i])
    return str(hash_val & 2147483647)


def get_picbo_and_richval(upload_result) -> tuple[str | None, str | None]:
    """从上传结果中提取图片的 picbo 和 richval 值用于发表图片说说"""
    if not isinstance(upload_result, dict) or 'ret' not in upload_result:
        logger.error("获取图片 picbo 和 richval 失败: 返回数据不合法")
        return None, None
    if upload_result.get('ret') != 0:
        logger.error(f"上传图片失败: {upload_result}")
        return None, None

    try:
        picbo = upload_result['data']['url'].split('&bo=')[1]
        richval = ",{},{},{},{},{},{},,{},{}".format(
            upload_result['data']['albumid'], upload_result['data']['lloc'],
            upload_result['data']['sloc'], upload_result['data']['type'],
            upload_result['data']['height'], upload_result['data']['width'],
            upload_result['data']['height'], upload_result['data']['width']
        )
        return picbo, richval
    except (KeyError, IndexError) as e:
        logger.error(f"提取 picbo 和 richval 失败: {e}")
        return None, None


def extract_code_html(html_content: str) -> Any | None:
    """从 QQ 空间响应的 HTML 内容中提取响应码 code 的值"""
    try:
        soup = bs4.BeautifulSoup(html_content, 'html.parser')
        script_tags = soup.find_all('script')
        for script in script_tags:
            if script.string and 'frameElement.callback' in script.string:
                script_content = script.string
                start_index = script_content.find('frameElement.callback(') + len('frameElement.callback(')
                end_index = script_content.rfind(');')
                if 0 < start_index < end_index:
                    json_str = script_content[start_index:end_index].strip()
                    if json_str.endswith(';'):
                        json_str = json_str[:-1]
                    data = json5.loads(json_str)
                    if isinstance(data, dict) and 'code' in data:
                        return data.get("code")
                    else:
                        continue
        return None
    except Exception:
        return None


def extract_code_json(json_response) -> Any | None:
    """从 QQ 空间响应的 json 内容中提取 code 值，如果不存在则返回 None"""
    try:
        if isinstance(json_response, str):
            data = json.loads(json_response)
        else:
            data = json_response
        return data.get('code', None)
    except (json.JSONDecodeError, KeyError, AttributeError):
        return None


def image_to_base64(image: bytes) -> str:
    """将图片转换为 base64 字符串"""
    pic_base64 = base64.b64encode(image)
    return str(pic_base64)[2:-1]


# ============================================================================
# QzoneAPI 类
# ============================================================================

class QzoneAPI:
    """QQ 空间 API 封装"""

    # QQ 空间 url 常量
    UPLOAD_IMAGE_URL = "https://up.qzone.qq.com/cgi-bin/upload/cgi_upload_image"
    EMOTION_PUBLISH_URL = "https://user.qzone.qq.com/proxy/domain/taotao.qzone.qq.com/cgi-bin/emotion_cgi_publish_v6"
    DOLIKE_URL = "https://user.qzone.qq.com/proxy/domain/w.qzone.qq.com/cgi-bin/likes/internal_dolike_app"
    COMMENT_URL = "https://user.qzone.qq.com/proxy/domain/taotao.qzone.qq.com/cgi-bin/emotion_cgi_re_feeds"
    REPLY_URL = "https://h5.qzone.qq.com/proxy/domain/taotao.qzone.qq.com/cgi-bin/emotion_cgi_re_feeds"
    LIST_URL = "https://user.qzone.qq.com/proxy/domain/taotao.qq.com/cgi-bin/emotion_cgi_msglist_v6"
    ZONE_LIST_URL = "https://user.qzone.qq.com/proxy/domain/ic2.qzone.qq.com/cgi-bin/feeds/feeds3_html_more"

    def __init__(self, cookies_dict: dict = {}):
        self.cookies = cookies_dict
        self.uin = self.cookies.get("uin", "").lstrip("o0")
        if self.uin == "":
            logger.error("未找到 uin，请检查 cookies 是否正确")
            return
        self.qq_nickname = ""
        self.gtk2 = ''

        if 'p_skey' in self.cookies:
            self.gtk2 = generate_gtk(self.cookies['p_skey'])

    async def get_image_base64_by_url(self, url: str) -> str | None:
        """从指定的 URL 获取图片并将其转换为 Base64 编码格式"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "https://qzone.qq.com/"
        }
        async with httpx.AsyncClient(follow_redirects=True) as client:
            request = httpx.Request("GET", url, headers=headers)
            response = await client.send(request)

        if response.status_code != 200:
            logger.error(f"请求失败: {response.url} 状态码: {response.status_code}")
            return None

        return base64.b64encode(response.content).decode('utf-8')

    async def upload_image(self, image: bytes) -> str | None:
        """上传图片到 QQ 空间"""
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            res = await client.request(
                method="POST",
                url=self.UPLOAD_IMAGE_URL,
                data={
                    "filename": "filename",
                    "zzpanelkey": "",
                    "uploadtype": "1",
                    "albumtype": "7",
                    "exttype": "0",
                    "skey": self.cookies["skey"],
                    "zzpaneluin": self.uin,
                    "p_uin": self.uin,
                    "uin": self.uin,
                    "p_skey": self.cookies['p_skey'],
                    "output_type": "json",
                    "qzonetoken": "",
                    "refer": "shuoshuo",
                    "charset": "utf-8",
                    "output_charset": "utf-8",
                    "upload_hd": "1",
                    "hd_width": "2048",
                    "hd_height": "10000",
                    "hd_quality": "96",
                    "backUrls": "http://upbak.photo.qzone.qq.com/cgi-bin/upload/cgi_upload_image,"
                                "http://119.147.64.75/cgi-bin/upload/cgi_upload_image",
                    "url": "https://up.qzone.qq.com/cgi-bin/upload/cgi_upload_image?g_tk=" + self.gtk2,
                    "base64": "1",
                    "picfile": image_to_base64(image),
                },
                headers={
                    'referer': 'https://user.qzone.qq.com/' + str(self.uin),
                    'origin': 'https://user.qzone.qq.com'
                },
                cookies=self.cookies
            )
        if res.status_code == 200:
            logger.debug(f"上传图片响应: {res.text}")
            try:
                return eval(res.text[res.text.find('{'):res.text.rfind('}') + 1])
            except Exception as e:
                logger.error(f"解析上传响应失败: {e}")
                return None
        else:
            logger.error(f"上传图片失败: 状态码 {res.status_code}")
            return None

    async def publish_emotion(self, content: str, images: list[bytes] | None = None) -> str | None:
        """将说说内容和图片上传到 QQ 空间"""
        if images is None:
            images = []

        post_data = {
            "syn_tweet_verson": "1",
            "paramstr": "1",
            "who": "1",
            "con": content,
            "feedversion": "1",
            "ver": "1",
            "ugc_right": "1",
            "to_sign": "0",
            "hostuin": self.uin,
            "code_version": "1",
            "format": "json",
            "qzreferrer": "https://user.qzone.qq.com/" + str(self.uin)
        }

        if len(images) > 0:
            pic_bos = []
            richvals = []
            for img in images:
                upload_result = await self.upload_image(img)
                if upload_result:
                    picbo, richval = get_picbo_and_richval(upload_result)
                    if picbo and richval:
                        pic_bos.append(picbo)
                        richvals.append(richval)

            if pic_bos:
                post_data['pic_bo'] = ','.join(pic_bos)
                post_data['richtype'] = '1'
                post_data['richval'] = '\t'.join(richvals)

        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            res = await client.request(
                method="POST",
                url=self.EMOTION_PUBLISH_URL,
                params={
                    'g_tk': self.gtk2,
                    'uin': self.uin,
                },
                data=post_data,
                headers={
                    'referer': 'https://user.qzone.qq.com/' + str(self.uin),
                    'origin': 'https://user.qzone.qq.com'
                },
                cookies=self.cookies
            )
        if res.status_code == 200:
            if extract_code_json(res.text) != 0:
                logger.error(f"发表说说失败，响应内容: {res.text}")
                return None
            try:
                return res.json().get('tid')
            except Exception as e:
                logger.error(f"解析发表结果失败: {e}")
                return None
        else:
            logger.error(f"发表说说失败: 状态码 {res.status_code} 内容: {res.text}")
            return None

    async def like(self, fid: str, target_qq: str) -> bool:
        """点赞指定说说"""
        uin = self.uin
        post_data = {
            'qzreferrer': f'https://user.qzone.qq.com/{uin}',
            'opuin': uin,
            'unikey': f'http://user.qzone.qq.com/{target_qq}/mood/{fid}',
            'curkey': f'http://user.qzone.qq.com/{target_qq}/mood/{fid}',
            'appid': 311,
            'from': 1,
            'typeid': 0,
            'abstime': int(time.time()),
            'fid': fid,
            'active': 0,
            'format': 'json',
            'fupdate': 1,
        }
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            res = await client.request(
                method="POST",
                url=self.DOLIKE_URL,
                params={'g_tk': self.gtk2},
                data=post_data,
                headers={
                    'referer': 'https://user.qzone.qq.com/' + str(self.uin),
                    'origin': 'https://user.qzone.qq.com'
                },
                cookies=self.cookies
            )
        if res.status_code == 200:
            if extract_code_json(res.text) != 0:
                logger.error("点赞失败" + res.text)
                return False
            return True
        else:
            logger.error("点赞失败: " + res.text)
            return False

    async def comment(self, fid: str, target_qq: str, content: str) -> bool:
        """评论指定说说"""
        uin = self.uin
        post_data = {
            "topicId": f'{target_qq}_{fid}__1',
            "uin": uin,
            "hostUin": target_qq,
            "feedsType": 100,
            "inCharset": "utf-8",
            "outCharset": "utf-8",
            "plat": "qzone",
            "source": "ic",
            "platformid": 52,
            "format": "fs",
            "ref": "feeds",
            "content": content,
        }
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            res = await client.request(
                method="POST",
                url=self.COMMENT_URL,
                params={"g_tk": self.gtk2},
                data=post_data,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
                    'referer': 'https://user.qzone.qq.com/' + str(self.uin),
                    'origin': 'https://user.qzone.qq.com'
                },
                cookies=self.cookies
            )
        if res.status_code == 200:
            if extract_code_html(res.text) != 0:
                logger.error("评论失败" + res.text)
                return False
            return True
        else:
            logger.error("评论失败: " + res.text)
            return False

    async def reply(self, fid: str, target_qq: str, target_nickname: str, content: str, comment_tid: str) -> bool:
        """回复指定评论"""
        uin = self.uin
        post_data = {
            "topicId": f"{uin}_{fid}__1",
            "uin": uin,
            "hostUin": uin,
            "content": f"回复@ {target_nickname} ：{content}",
            "format": "fs",
            "plat": "qzone",
            "source": "ic",
            "platformid": 52,
            "ref": "feeds",
            "richtype": "",
            "richval": "",
            "paramstr": f"@{target_nickname}",
        }
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            res = await client.request(
                method="POST",
                url=self.REPLY_URL,
                params={"g_tk": self.gtk2},
                data=post_data,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
                },
                cookies=self.cookies
            )
        if res.status_code == 200:
            if extract_code_html(res.text) != 0:
                logger.error("回复失败" + res.text)
                return False
            return True
        else:
            logger.error(f"回复失败，错误码: {res.status_code}")
            return False

    async def get_list(self, target_qq: str, num: int, filter: bool = True) -> list[dict[str, Any]]:
        """获取指定 QQ 号的好友说说列表"""
        logger.info(f'即将获取 {target_qq} 的说说列表...num={num} filter={filter}')
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            res = await client.request(
                method="GET",
                url=self.LIST_URL,
                params={
                    'g_tk': self.gtk2,
                    "uin": target_qq,
                    "ftype": 0,
                    "sort": 0,
                    "pos": 0,
                    "num": num,
                    "replynum": 100,
                    "callback": "_preloadCallback",
                    "code_version": 1,
                    "format": "jsonp",
                    "need_comment": 1,
                    "need_private_comment": 1
                },
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/91.0.4472.124 Safari/537.36",
                    "Referer": f"https://user.qzone.qq.com/{target_qq}",
                    "Host": "user.qzone.qq.com",
                    "Connection": "keep-alive"
                },
                cookies=self.cookies
            )

        if res.status_code != 200:
            logger.error("访问失败: " + str(res.status_code))
            return []

        data = res.text
        if data.startswith('_preloadCallback(') and data.endswith(');'):
            json_str = data[len('_preloadCallback('):-2]
        else:
            json_str = data

        try:
            json_data = json.loads(json_str)
            logger.debug(f"原始说说数据: {json_data}")
            uin_nickname = json_data.get('logininfo').get('name')
            self.qq_nickname = uin_nickname

            if json_data.get('code') != 0:
                return [{"error": json_data.get('message')}]

            feeds_list = []
            msglist = json_data.get("msglist") or []
            if not msglist:
                logger.warning("msglist 为空或 None，返回空的说说列表")
            for msg in msglist:
                is_comment = False
                if 'commentlist' in msg:
                    commentlist = msg.get("commentlist")
                    if isinstance(commentlist, list):
                        for comment in commentlist:
                            qq_nickname = comment.get("name")
                            if uin_nickname == qq_nickname and target_qq != str(self.uin) and filter:
                                logger.info('已评论过此说说，即将跳过')
                                is_comment = True
                                break

                if not is_comment or not filter:
                    timestamp = msg.get("created_time", "")
                    if timestamp:
                        time_tuple = time.localtime(timestamp)
                        created_time = time.strftime('%Y-%m-%d %H:%M:%S', time_tuple)
                    else:
                        created_time = msg.get("createTime", "unknown")
                    tid = msg.get("tid", "")
                    content = msg.get("content", "")
                    logger.info(f"正在阅读说说内容: {content[:20]}...")

                    # 提取图片信息
                    images = []
                    for pic in (msg.get("pic") or []):
                        url = pic.get("url1") or pic.get("pic_id") or pic.get("smallurl")
                        if url:
                            try:
                                image_base64 = await self.get_image_base64_by_url(url)
                                if image_base64:
                                    images.append(image_base64)
                            except Exception as img_err:
                                logger.warning(f"获取图片失败: {img_err}")

                    # 读取视频封面
                    for video in (msg.get("video") or []):
                        video_image_url = video.get("url1") or video.get("pic_url")
                        if video_image_url:
                            try:
                                image_base64 = await self.get_image_base64_by_url(video_image_url)
                                if image_base64:
                                    images.append(image_base64)
                            except Exception as img_err:
                                logger.warning(f"获取视频封面失败: {img_err}")

                    # 提取视频播放地址
                    videos = []
                    for video in (msg.get("video") or []):
                        url = video.get("url3")
                        if url:
                            videos.append(url)

                    # 提取转发内容
                    rt_con = ""
                    rt_data = msg.get("rt_con") or {}
                    if isinstance(rt_data, dict):
                        rt_con = rt_data.get("content", "")

                    # 提取评论
                    def _safe_int(value):
                        try:
                            return int(value)
                        except (TypeError, ValueError):
                            return None

                    comments = []
                    for comment in (msg.get("commentlist") or []):
                        comment_nickname = comment.get("name", "")
                        comment_content = comment.get("content", "")
                        comment_uin = comment.get("uin", "")
                        comment_tid_value = _safe_int(comment.get("tid"))
                        comment_time = comment.get("createTime", "") or comment.get("createTime2", "")

                        for sub_comment in (comment.get("list_3") or []):
                            sub_content = sub_comment.get("content", "")
                            sub_nickname = sub_comment.get("name", "")
                            sub_uin = sub_comment.get("uin", "")
                            sub_tid_value = _safe_int(sub_comment.get("tid"))
                            sub_time = sub_comment.get("createTime", "") or comment.get("createTime2", "")
                            sub_parent = comment_tid_value
                            comments.append({
                                "content": sub_content,
                                "qq_account": str(sub_uin),
                                "nickname": sub_nickname,
                                "comment_tid": sub_tid_value,
                                "created_time": sub_time,
                                "parent_tid": sub_parent,
                            })

                        comments.append({
                            "content": comment_content,
                            "qq_account": str(comment_uin),
                            "nickname": comment_nickname,
                            "comment_tid": comment_tid_value,
                            "created_time": comment_time,
                            "parent_tid": None,
                        })

                    feeds_list.append({
                        "target_qq": str(target_qq),
                        "tid": str(tid),
                        "created_time": created_time,
                        "content": content,
                        "images": images,
                        "videos": videos,
                        "rt_con": rt_con,
                        "comments": comments
                    })
            if len(feeds_list) == 0:
                return [{"error": '你已经看过最近的所有说说了，没有必要再看一遍'}]
            return feeds_list

        except Exception as e:
            logger.error(str(json_data))
            return [{"error": f'{e},你没有看到任何东西'}]

    async def get_list_lite(self, target_qq: str, num: int, filter: bool = True) -> list[dict[str, Any]]:
        """获取指定 QQ 号的好友说说列表（轻量版，图片仅保留 URL，不下载 base64）"""
        logger.info(f'[LITE] 即将获取 {target_qq} 的说说列表...num={num} filter={filter}')
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            res = await client.request(
                method="GET",
                url=self.LIST_URL,
                params={
                    'g_tk': self.gtk2,
                    "uin": target_qq,
                    "ftype": 0,
                    "sort": 0,
                    "pos": 0,
                    "num": num,
                    "replynum": 100,
                    "callback": "_preloadCallback",
                    "code_version": 1,
                    "format": "jsonp",
                    "need_comment": 1,
                    "need_private_comment": 1
                },
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/91.0.4472.124 Safari/537.36",
                    "Referer": f"https://user.qzone.qq.com/{target_qq}",
                    "Host": "user.qzone.qq.com",
                    "Connection": "keep-alive"
                },
                cookies=self.cookies
            )

        if res.status_code != 200:
            logger.error("访问失败: " + str(res.status_code))
            return []

        data = res.text
        if data.startswith('_preloadCallback(') and data.endswith(');'):
            json_str = data[len('_preloadCallback('):-2]
        else:
            json_str = data

        try:
            json_data = json.loads(json_str)
            uin_nickname = json_data.get('logininfo').get('name')
            self.qq_nickname = uin_nickname

            if json_data.get('code') != 0:
                return [{"error": json_data.get('message')}]

            feeds_list = []
            msglist = json_data.get("msglist") or []
            if not msglist:
                logger.warning("msglist 为空或 None，返回空的说说列表")
            for msg in msglist:
                is_comment = False
                if 'commentlist' in msg:
                    commentlist = msg.get("commentlist")
                    if isinstance(commentlist, list):
                        for comment in commentlist:
                            qq_nickname = comment.get("name")
                            if uin_nickname == qq_nickname and target_qq != str(self.uin) and filter:
                                logger.info('已评论过此说说，即将跳过')
                                is_comment = True
                                break

                if not is_comment or not filter:
                    timestamp = msg.get("created_time", "")
                    if timestamp:
                        time_tuple = time.localtime(timestamp)
                        created_time = time.strftime('%Y-%m-%d %H:%M:%S', time_tuple)
                    else:
                        created_time = msg.get("createTime", "unknown")
                    tid = msg.get("tid", "")
                    content = msg.get("content", "")
                    logger.info(f"正在阅读说说内容: {content[:20]}...")

                    # 提取图片 URL（不下载 base64）
                    image_urls = []
                    for pic in (msg.get("pic") or []):
                        url = pic.get("url1") or pic.get("pic_id") or pic.get("smallurl")
                        if url:
                            image_urls.append(url)

                    # 读取视频封面 URL
                    for video in (msg.get("video") or []):
                        video_image_url = video.get("url1") or video.get("pic_url")
                        if video_image_url:
                            image_urls.append(video_image_url)

                    # 提取视频播放地址
                    videos = []
                    for video in (msg.get("video") or []):
                        url = video.get("url3")
                        if url:
                            videos.append(url)

                    # 提取转发内容
                    rt_con = ""
                    rt_data = msg.get("rt_con") or {}
                    if isinstance(rt_data, dict):
                        rt_con = rt_data.get("content", "")

                    # 提取评论
                    def _safe_int(value):
                        try:
                            return int(value)
                        except (TypeError, ValueError):
                            return None

                    comments = []
                    for comment in (msg.get("commentlist") or []):
                        comment_nickname = comment.get("name", "")
                        comment_content = comment.get("content", "")
                        comment_uin = comment.get("uin", "")
                        comment_tid_value = _safe_int(comment.get("tid"))
                        comment_time = comment.get("createTime", "") or comment.get("createTime2", "")

                        for sub_comment in (comment.get("list_3") or []):
                            sub_content = sub_comment.get("content", "")
                            sub_nickname = sub_comment.get("name", "")
                            sub_uin = sub_comment.get("uin", "")
                            sub_tid_value = _safe_int(sub_comment.get("tid"))
                            sub_time = sub_comment.get("createTime", "") or comment.get("createTime2", "")
                            sub_parent = comment_tid_value
                            comments.append({
                                "content": sub_content,
                                "qq_account": str(sub_uin),
                                "nickname": sub_nickname,
                                "comment_tid": sub_tid_value,
                                "created_time": sub_time,
                                "parent_tid": sub_parent,
                            })

                        comments.append({
                            "content": comment_content,
                            "qq_account": str(comment_uin),
                            "nickname": comment_nickname,
                            "comment_tid": comment_tid_value,
                            "created_time": comment_time,
                            "parent_tid": None,
                        })

                    feeds_list.append({
                        "target_qq": str(target_qq),
                        "tid": str(tid),
                        "created_time": created_time,
                        "content": content,
                        "images": image_urls,
                        "videos": videos,
                        "rt_con": rt_con,
                        "comments": comments
                    })
            if len(feeds_list) == 0:
                return [{"error": '你已经看过最近的所有说说了，没有必要再看一遍'}]
            return feeds_list

        except Exception as e:
            logger.error(str(json_data))
            return [{"error": f'{e},你没有看到任何东西'}]

    async def get_feeds_summary(self, target_qq: str, num: int, filter: bool = True) -> list[dict[str, Any]]:
        """获取说说摘要列表（超精简版，仅含 tid/时间/内容预览/图片数量/评论数）"""
        feeds = await self.get_list_lite(target_qq, num, filter)
        if not feeds or (len(feeds) == 1 and "error" in feeds[0]):
            return feeds

        summaries = []
        for feed in feeds:
            content = feed.get("content", "")
            preview = content[:100] + "..." if len(content) > 100 else content
            summaries.append({
                "tid": feed.get("tid", ""),
                "created_time": feed.get("created_time", ""),
                "preview": preview,
                "image_count": len(feed.get("images", [])),
                "video_count": len(feed.get("videos", [])),
                "comment_count": len(feed.get("comments", [])),
                "is_forward": bool(feed.get("rt_con", "")),
            })
        return summaries

    async def get_feed_detail(self, target_qq: str, tid: str) -> dict[str, Any] | None:
        """获取单条说说的完整数据（含图片 base64），通过 tid 定位"""
        # 获取最近 20 条说说（含图片 base64），从中筛选匹配的 tid
        feeds = await self.get_list(target_qq, 20, filter=False)
        if not feeds:
            return None
        for feed in feeds:
            if feed.get("tid") == tid:
                return feed
        return None

    async def get_qzone_list(self) -> list[dict[str, Any]]:
        """获取自己的 QQ 空间下，好友最新的几条说说"""
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            res = await client.request(
                method="GET",
                url=self.ZONE_LIST_URL,
                params={
                    "uin": self.uin,
                    "scope": 0,
                    "view": 1,
                    "filter": "all",
                    "flag": 1,
                    "applist": "all",
                    "pagenum": 1,
                    "aisortEndTime": 0,
                    "aisortOffset": 0,
                    "aisortBeginTime": 0,
                    "begintime": 0,
                    "format": "json",
                    "g_tk": self.gtk2,
                    "useutf8": 1,
                    "outputhtmlfeed": 1
                },
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/91.0.4472.124 Safari/537.36",
                    "Referer": f"https://user.qzone.qq.com/{self.uin}",
                    "Host": "user.qzone.qq.com",
                    "Connection": "keep-alive"
                },
                cookies=self.cookies
            )

        if res.status_code != 200:
            logger.error("访问失败: " + str(res.status_code))
            return []

        data = res.text
        if data.startswith('_Callback(') and data.endswith(');'):
            data = data[len('_Callback('):-2]
        data = data.replace('undefined', 'null')
        try:
            data_dict = json5.loads(data)
            if isinstance(data_dict, dict):
                data_json = data_dict.get('data', {}).get('data', [])
            else:
                logger.error("无效的 JSON 数据")
                return []
        except Exception as e:
            logger.error(f"解析错误: {e}")
            return []

        try:
            feeds_list = []
            for feed in data_json:
                if not feed:
                    continue
                appid = str(feed.get('appid', ''))
                if appid != '311':
                    continue
                target_qq = feed.get('uin', '')
                tid = feed.get('key', '')
                if not target_qq or not tid:
                    logger.error(f"无效的说说数据: target_qq={target_qq}, tid={tid}")
                    continue

                html_content = feed.get('html', '')
                if not html_content:
                    logger.error(f"说说内容为空: UIN={target_qq}, TID={tid}")
                    continue

                soup = bs4.BeautifulSoup(html_content, 'html.parser')
                created_time = feed.get('feedstime', '').strip()

                text_div = soup.find('div', class_='f-info')
                text = text_div.get_text(strip=True) if text_div else ""

                rt_con = ""
                txt_box = soup.select_one('div.txt-box')
                if txt_box:
                    rt_con = txt_box.get_text(strip=True)
                    if '：' in rt_con:
                        rt_con = rt_con.split('：', 1)[1].strip()

                image_urls = []
                img_box = soup.find('div', class_='img-box')
                if img_box:
                    for img in img_box.find_all('img'):
                        src = img.get('src')
                        if src and isinstance(src, str) and not src.startswith('http://qzonestyle.gtimg.cn'):
                            image_urls.append(src)

                img_tag = soup.select_one('div.video-img img')
                if img_tag and 'src' in img_tag.attrs:
                    image_urls.append(img_tag['src'])

                unique_urls = list(set(image_urls))
                images = []
                for url in unique_urls:
                    try:
                        image_base64 = await self.get_image_base64_by_url(url)
                        if image_base64:
                            images.append(image_base64)
                    except Exception as e:
                        logger.info(f'图片识别失败: {url} - {str(e)}')

                videos = []
                video_div = soup.select_one('div.img-box.f-video-wrap.play')
                if video_div and 'url3' in video_div.attrs:
                    videos.append(video_div['url3'])

                comments_list = []
                comment_items = soup.select('li.comments-item.bor3')
                if comment_items:
                    for item in comment_items:
                        qq_account = item.get('data-uin', '')
                        comment_tid = item.get('data-tid', '')
                        nickname = item.get('data-nick', '')

                        content_div = item.select_one('div.comments-content')
                        if content_div:
                            for op in content_div.select('div.comments-op'):
                                op.decompose()
                            content = content_div.get_text(' ', strip=True)
                        else:
                            content = ""

                        comment_time_span = item.select_one('span.state')
                        comment_time = comment_time_span.get_text(strip=True) if comment_time_span else ""

                        parent_tid = None
                        parent_div = item.find_parent('div', class_='mod-comments-sub')
                        if parent_div:
                            parent_li = parent_div.find_parent('li', class_='comments-item')
                            if parent_li:
                                parent_tid = parent_li.get('data-tid')

                        comments_list.append({
                            'qq_account': str(qq_account),
                            'nickname': nickname,
                            'comment_tid': int(comment_tid) if isinstance(comment_tid, str) and comment_tid.isdigit() else 0,
                            'content': content,
                            "created_time": comment_time,
                            'parent_tid': int(parent_tid) if isinstance(parent_tid, str) and parent_tid.isdigit() else None
                        })

                feeds_list.append({
                    'target_qq': str(target_qq),
                    'tid': str(tid),
                    "created_time": created_time,
                    'content': text,
                    'images': images,
                    'videos': videos,
                    'rt_con': rt_con,
                    'comments': comments_list,
                })

            logger.info(f"成功解析 {len(feeds_list)} 条最新说说")
            feeds_list = [item for item in feeds_list if item.get('target_qq') != str(self.uin)]
            return feeds_list
        except Exception as e:
            logger.error(f'解析说说错误：{str(e)}')
            return []

    async def get_qzone_list_lite(self) -> list[dict[str, Any]]:
        """获取自己的 QQ 空间下好友最新说说（轻量版，图片仅保留 URL，不下载 base64）"""
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            res = await client.request(
                method="GET",
                url=self.ZONE_LIST_URL,
                params={
                    "uin": self.uin,
                    "scope": 0,
                    "view": 1,
                    "filter": "all",
                    "flag": 1,
                    "applist": "all",
                    "pagenum": 1,
                    "aisortEndTime": 0,
                    "aisortOffset": 0,
                    "aisortBeginTime": 0,
                    "begintime": 0,
                    "format": "json",
                    "g_tk": self.gtk2,
                    "useutf8": 1,
                    "outputhtmlfeed": 1
                },
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/91.0.4472.124 Safari/537.36",
                    "Referer": f"https://user.qzone.qq.com/{self.uin}",
                    "Host": "user.qzone.qq.com",
                    "Connection": "keep-alive"
                },
                cookies=self.cookies
            )

        if res.status_code != 200:
            logger.error("访问失败: " + str(res.status_code))
            return []

        data = res.text
        if data.startswith('_Callback(') and data.endswith(');'):
            data = data[len('_Callback('):-2]
        data = data.replace('undefined', 'null')
        try:
            data_dict = json5.loads(data)
            if isinstance(data_dict, dict):
                data_json = data_dict.get('data', {}).get('data', [])
            else:
                logger.error("无效的 JSON 数据")
                return []
        except Exception as e:
            logger.error(f"解析错误: {e}")
            return []

        try:
            feeds_list = []
            for feed in data_json:
                if not feed:
                    continue
                appid = str(feed.get('appid', ''))
                if appid != '311':
                    continue
                target_qq = feed.get('uin', '')
                tid = feed.get('key', '')
                if not target_qq or not tid:
                    logger.error(f"无效的说说数据: target_qq={target_qq}, tid={tid}")
                    continue

                html_content = feed.get('html', '')
                if not html_content:
                    logger.error(f"说说内容为空: UIN={target_qq}, TID={tid}")
                    continue

                soup = bs4.BeautifulSoup(html_content, 'html.parser')
                created_time = feed.get('feedstime', '').strip()

                text_div = soup.find('div', class_='f-info')
                text = text_div.get_text(strip=True) if text_div else ""

                rt_con = ""
                txt_box = soup.select_one('div.txt-box')
                if txt_box:
                    rt_con = txt_box.get_text(strip=True)
                    if '：' in rt_con:
                        rt_con = rt_con.split('：', 1)[1].strip()

                # Extract image URLs only (no base64 download)
                image_urls = []
                img_box = soup.find('div', class_='img-box')
                if img_box:
                    for img in img_box.find_all('img'):
                        src = img.get('src')
                        if src and isinstance(src, str) and not src.startswith('http://qzonestyle.gtimg.cn'):
                            image_urls.append(src)

                img_tag = soup.select_one('div.video-img img')
                if img_tag and 'src' in img_tag.attrs:
                    image_urls.append(img_tag['src'])

                unique_urls = list(set(image_urls))

                videos = []
                video_div = soup.select_one('div.img-box.f-video-wrap.play')
                if video_div and 'url3' in video_div.attrs:
                    videos.append(video_div['url3'])

                comments_list = []
                comment_items = soup.select('li.comments-item.bor3')
                if comment_items:
                    for item in comment_items:
                        qq_account = item.get('data-uin', '')
                        comment_tid = item.get('data-tid', '')
                        nickname = item.get('data-nick', '')

                        content_div = item.select_one('div.comments-content')
                        if content_div:
                            for op in content_div.select('div.comments-op'):
                                op.decompose()
                            content = content_div.get_text(' ', strip=True)
                        else:
                            content = ""

                        comment_time_span = item.select_one('span.state')
                        comment_time = comment_time_span.get_text(strip=True) if comment_time_span else ""

                        parent_tid = None
                        parent_div = item.find_parent('div', class_='mod-comments-sub')
                        if parent_div:
                            parent_li = parent_div.find_parent('li', class_='comments-item')
                            if parent_li:
                                parent_tid = parent_li.get('data-tid')

                        comments_list.append({
                            'qq_account': str(qq_account),
                            'nickname': nickname,
                            'comment_tid': int(comment_tid) if isinstance(comment_tid, str) and comment_tid.isdigit() else 0,
                            'content': content,
                            "created_time": comment_time,
                            'parent_tid': int(parent_tid) if isinstance(parent_tid, str) and parent_tid.isdigit() else None
                        })

                feeds_list.append({
                    'target_qq': str(target_qq),
                    'tid': str(tid),
                    "created_time": created_time,
                    'content': text,
                    'images': unique_urls,
                    'videos': videos,
                    'rt_con': rt_con,
                    'comments': comments_list,
                })

            logger.info(f"[LITE] 成功解析 {len(feeds_list)} 条最新说说")
            feeds_list = [item for item in feeds_list if item.get('target_qq') != str(self.uin)]
            return feeds_list
        except Exception as e:
            logger.error(f'解析说说错误：{str(e)}')
            return []

    async def get_send_history(self, num: int) -> str:
        """构建说说发送历史 prompt"""
        feeds_list = await self.get_list(target_qq=str(self.uin), num=num)
        history = "==================="
        for feed in feeds_list:
            if not feed.get("rt_con", ""):
                history += f"""
时间：'{feed.get("created_time", "")}'。
说说内容：'{feed.get("content", "")}'
图片：'{feed.get("images", [])}'
===================
"""
            else:
                history += f"""
时间: '{feed.get("created_time", "")}'。
转发了一条说说，内容为: '{feed.get("rt_con", "")}'
图片: '{feed.get("images", [])}'
对该说说的评论为: '{feed.get("content", "")}'
===================
"""
        return history


def create_qzone_api() -> QzoneAPI | None:
    """使用存在的 cookie 文件创建 QzoneAPI 实例并返回"""
    cookie_file = COOKIE_PATH
    if os.path.exists(cookie_file):
        try:
            with open(cookie_file, 'r') as f:
                cookies = json.load(f)
        except Exception as e:
            logger.error(f"读取 cookie 文件失败: {cookie_file}，错误: {e}")
            cookies = None
    else:
        logger.error(f"cookie 文件不存在: {cookie_file}")
        cookies = None

    if cookies:
        qzone = QzoneAPI(cookies)
        return qzone
    else:
        return None
