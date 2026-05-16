"""
QQ Space MCP Server 配置模块
支持 TOML 配置文件 + 环境变量覆盖
"""

import os
import sys
from pathlib import Path

# Python 3.11+ 内置 tomllib，低版本使用 tomli
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


# ============================================================================
# 配置路径
# ============================================================================

_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
_CONFIG_FILE = _CONFIG_DIR / "env.toml"
_TEMPLATE_FILE = _CONFIG_DIR / "template" / "config.toml"


# ============================================================================
# 配置加载
# ============================================================================

def _load_toml_config() -> dict:
    """加载 TOML 配置文件，优先 env.toml，回退到模板"""
    if _CONFIG_FILE.exists():
        with open(_CONFIG_FILE, "rb") as f:
            return tomllib.load(f)
    elif _TEMPLATE_FILE.exists():
        print(f"[WARN] 配置文件 {_CONFIG_FILE} 不存在，使用模板配置")
        with open(_TEMPLATE_FILE, "rb") as f:
            return tomllib.load(f)
    else:
        print("[WARN] 无配置文件，使用默认配置")
        return {}


_toml_config = _load_toml_config()


def _get_toml(key: str, default=None):
    """从 TOML 配置中获取嵌套键值，如 'plugin.http_host'"""
    keys = key.split(".")
    value = _toml_config
    for k in keys:
        if isinstance(value, dict):
            value = value.get(k)
        else:
            return default
        if value is None:
            return default
    return value


# ============================================================================
# 配置项（环境变量优先，回退到 TOML，再回退到默认值）
# ============================================================================

def _env_or_toml(env_key: str, toml_key: str, default=None, converter=None):
    """环境变量 > TOML > 默认值"""
    env_val = os.getenv(env_key)
    if env_val is not None:
        if converter:
            return converter(env_val)
        return env_val
    val = _get_toml(toml_key, default)
    if converter and val is not None:
        return converter(val)
    return val


# --- 插件基础配置 ---
HTTP_HOST: str = _env_or_toml("QZONE_HTTP_HOST", "plugin.http_host", "127.0.0.1")
HTTP_PORT: int = _env_or_toml("QZONE_HTTP_PORT", "plugin.http_port", 9999, converter=int)
NAPCAT_TOKEN: str = _env_or_toml("QZONE_NAPCAT_TOKEN", "plugin.napcat_token", "")

_cookie_methods_raw = _env_or_toml("QZONE_COOKIE_METHODS", "plugin.cookie_methods", None)
if _cookie_methods_raw is None:
    COOKIE_METHODS: list[str] = ["adapter", "napcat", "qrcode", "local"]
elif isinstance(_cookie_methods_raw, str):
    COOKIE_METHODS = [m.strip() for m in _cookie_methods_raw.split(",") if m.strip()]
else:
    COOKIE_METHODS = _cookie_methods_raw

# --- AI 生图配置 ---
IMAGE_ENABLED: bool = _env_or_toml("QZONE_IMAGE_ENABLED", "image.enabled", False, converter=lambda v: str(v).lower() in ("true", "1", "yes"))
IMAGE_BASE_URL: str = _env_or_toml("QZONE_IMAGE_BASE_URL", "image.base_url", "https://ark.cn-beijing.volces.com/api/v3")
IMAGE_MODEL: str = _env_or_toml("QZONE_IMAGE_MODEL", "image.model", "doubao-seedream-5-0-260128")
IMAGE_API_KEY: str = _env_or_toml("QZONE_IMAGE_API_KEY", "image.api_key", "your_api_key")
IMAGE_ENABLE_REFERENCE: bool = _env_or_toml("QZONE_IMAGE_ENABLE_REFERENCE", "image.enable_reference", False, converter=lambda v: str(v).lower() in ("true", "1", "yes"))
IMAGE_REFERENCE: str = _env_or_toml("QZONE_IMAGE_REFERENCE", "image.reference", "")


def print_config():
    """打印当前配置（隐藏敏感信息）"""
    print("=" * 60)
    print("QQ Space MCP Server 配置")
    print("=" * 60)
    print(f"  HTTP_HOST: {HTTP_HOST}")
    print(f"  HTTP_PORT: {HTTP_PORT}")
    print(f"  NAPCAT_TOKEN: {'***' if NAPCAT_TOKEN else '(空)'}")
    print(f"  COOKIE_METHODS: {COOKIE_METHODS}")
    print(f"  IMAGE_ENABLED: {IMAGE_ENABLED}")
    if IMAGE_ENABLED:
        print(f"  IMAGE_BASE_URL: {IMAGE_BASE_URL}")
        print(f"  IMAGE_MODEL: {IMAGE_MODEL}")
        print(f"  IMAGE_API_KEY: {'***' if IMAGE_API_KEY else '(空)'}")
        print(f"  IMAGE_ENABLE_REFERENCE: {IMAGE_ENABLE_REFERENCE}")
        print(f"  IMAGE_REFERENCE: {IMAGE_REFERENCE}")
    print("=" * 60)
