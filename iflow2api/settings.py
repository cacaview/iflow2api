"""应用配置管理 - 使用 ~/.iflow/settings.json 统一管理配置"""

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from .config import load_iflow_config, save_iflow_config, IFlowConfig
from .autostart import set_auto_start as _set_auto_start
from .autostart import get_auto_start as _get_auto_start
from .autostart import is_auto_start_supported, get_platform_name


class AppSettings(BaseModel):
    """应用配置修"""

    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 28000

    # iFlow 配置 (从 ~/.iflow/settings.json 读取)
    api_key: str = ""
    base_url: str = "https://apis.iflow.cn/v1"

    # OAuth 配置 (从 ~/.iflow/settings.json 读取)
    auth_type: str = "api-key"  # 认证类型: oauth-iflow, api-key, openai-compatible
    oauth_access_token: str = ""  # OAuth 访问令牌
    oauth_refresh_token: str = ""  # OAuth 刷新令牌
    oauth_expires_at: Optional[str] = None  # OAuth token 过期时间 (ISO 格式)

    # 应用设置 (保存到 ~/.iflow2api/config.json)
    auto_start: bool = False  # 开机自启动
    start_minimized: bool = False  # 启动时最小化
    # 关闭按钮行为: "exit"=直接退出, "minimize_to_tray"=最小化到托盘, "minimize_to_taskbar"=最小化到任务栏
    close_action: str = "minimize_to_tray"
    auto_run_server: bool = False  # 启动时自动运行服务

    # 主题设置
    theme_mode: str = "system"  # 主题模式: light, dark, system

    # 速率限制设置
    rate_limit_enabled: bool = True  # 是否启用速率限制
    rate_limit_per_minute: int = 60  # 每分钟最大请求数
    rate_limit_per_hour: int = 1000  # 每小时最大请求数
    rate_limit_per_day: int = 10000  # 每天最大请求数

    # 思考链（Chain of Thought）设置
    # 当模型返回 reasoning_content 时：
    # - False: 将 reasoning_content 合并到 content，确保 OpenAI 兼容客户端正常工作
    # - True（默认）: 保留 reasoning_content 字段，客户端可分别处理思考过程和最终回答
    preserve_reasoning_content: bool = True

    # 语言设置
    language: str = "zh"  # 界面语言: zh, en

    # 更新检查设置
    check_update_on_startup: bool = True  # 启动时检查更新
    skip_version: str = ""  # 跳过的版本号

    # 自定义 API 鉴权设置
    custom_api_key: str = ""  # 自定义 API 密钥，留空则不验证
    custom_auth_header: str = "Authorization"  # 自定义授权标头名称


def get_config_dir() -> Path:
    """获取应用配置目录"""
    return Path.home() / ".iflow2api"


def get_config_path() -> Path:
    """获取应用配置文件路径"""
    return get_config_dir() / "config.json"


def load_settings() -> AppSettings:
    """加载配置"""
    settings = AppSettings()

    # 首先从 ~/.iflow2api/config.json 加载所有设置（包括 api_key）
    app_config_path = get_config_path()
    if app_config_path.exists():
        try:
            with open(app_config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 加载所有设置
                if "host" in data:
                    settings.host = data["host"]
                if "port" in data:
                    settings.port = data["port"]
                # api_key 和 base_url 也保存在 iflow2api/config.json 中
                if "api_key" in data:
                    settings.api_key = data["api_key"]
                if "base_url" in data:
                    settings.base_url = data["base_url"]
                if "auto_start" in data:
                    settings.auto_start = data["auto_start"]
                if "start_minimized" in data:
                    settings.start_minimized = data["start_minimized"]
                if "close_action" in data:
                    settings.close_action = data["close_action"]
                elif "minimize_to_tray" in data:
                    # 兼容旧配置：minimize_to_tray=True -> close_action="minimize_to_tray"
                    # minimize_to_tray=False -> close_action="exit"
                    settings.close_action = "minimize_to_tray" if data["minimize_to_tray"] else "exit"
                if "auto_run_server" in data:
                    settings.auto_run_server = data["auto_run_server"]
                if "theme_mode" in data:
                    settings.theme_mode = data["theme_mode"]
                # 速率限制设置
                if "rate_limit_enabled" in data:
                    settings.rate_limit_enabled = data["rate_limit_enabled"]
                if "rate_limit_per_minute" in data:
                    settings.rate_limit_per_minute = data["rate_limit_per_minute"]
                if "rate_limit_per_hour" in data:
                    settings.rate_limit_per_hour = data["rate_limit_per_hour"]
                if "rate_limit_per_day" in data:
                    settings.rate_limit_per_day = data["rate_limit_per_day"]
                # 语言设置
                if "language" in data:
                    settings.language = data["language"]
                # 思考链设置
                if "preserve_reasoning_content" in data:
                    settings.preserve_reasoning_content = data["preserve_reasoning_content"]
                # OAuth 设置
                if "auth_type" in data:
                    settings.auth_type = data["auth_type"]
                if "oauth_access_token" in data:
                    settings.oauth_access_token = data["oauth_access_token"]
                if "oauth_refresh_token" in data:
                    settings.oauth_refresh_token = data["oauth_refresh_token"]
                if "oauth_expires_at" in data:
                    settings.oauth_expires_at = data["oauth_expires_at"]
                # 更新检查设置
                if "check_update_on_startup" in data:
                    settings.check_update_on_startup = data["check_update_on_startup"]
                if "skip_version" in data:
                    settings.skip_version = data["skip_version"]
                # 自定义 API 鉴权设置
                if "custom_api_key" in data:
                    settings.custom_api_key = data["custom_api_key"]
                if "custom_auth_header" in data:
                    settings.custom_auth_header = data["custom_auth_header"]
        except Exception:
            pass

    # 如果 api_key 为空，尝试从 ~/.iflow/settings.json 加载
    if not settings.api_key:
        try:
            iflow_config = load_iflow_config()
            if iflow_config.api_key:
                settings.api_key = iflow_config.api_key
            if iflow_config.base_url:
                settings.base_url = iflow_config.base_url
            if iflow_config.auth_type:
                settings.auth_type = iflow_config.auth_type
            if iflow_config.oauth_access_token:
                settings.oauth_access_token = iflow_config.oauth_access_token
            if iflow_config.oauth_refresh_token:
                settings.oauth_refresh_token = iflow_config.oauth_refresh_token
            if iflow_config.oauth_expires_at:
                settings.oauth_expires_at = iflow_config.oauth_expires_at.isoformat()
        except Exception:
            pass

    return settings


def save_settings(settings: AppSettings) -> None:
    """
    保存配置

    所有设置都保存到 ~/.iflow2api/config.json
    同时也保存到 ~/.iflow/settings.json 以保持兼容性
    """
    # 1. 保存所有设置到 ~/.iflow2api/config.json
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    app_data = {
        "host": settings.host,
        "port": settings.port,
        # iFlow 配置也保存到 iflow2api/config.json
        "api_key": settings.api_key,
        "base_url": settings.base_url,
        # OAuth 配置
        "auth_type": settings.auth_type,
        "oauth_access_token": settings.oauth_access_token,
        "oauth_refresh_token": settings.oauth_refresh_token,
        "oauth_expires_at": settings.oauth_expires_at,
        # 应用设置
        "auto_start": settings.auto_start,
        "start_minimized": settings.start_minimized,
        "close_action": settings.close_action,
        "auto_run_server": settings.auto_run_server,
        "theme_mode": settings.theme_mode,
        # 速率限制设置
        "rate_limit_enabled": settings.rate_limit_enabled,
        "rate_limit_per_minute": settings.rate_limit_per_minute,
        "rate_limit_per_hour": settings.rate_limit_per_hour,
        "rate_limit_per_day": settings.rate_limit_per_day,
        # 思考链设置
        "preserve_reasoning_content": settings.preserve_reasoning_content,
        # 语言设置
        "language": settings.language,
        # 更新检查设置
        "check_update_on_startup": settings.check_update_on_startup,
        "skip_version": settings.skip_version,
        # 自定义 API 鉴权设置
        "custom_api_key": settings.custom_api_key,
        "custom_auth_header": settings.custom_auth_header,
    }

    config_path = get_config_path()
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(app_data, f, indent=2, ensure_ascii=False)

    # 2. 同时保存到 ~/.iflow/settings.json 以保持兼容性
    try:
        existing_config = load_iflow_config()
    except (FileNotFoundError, ValueError):
        existing_config = IFlowConfig(api_key="", base_url="https://apis.iflow.cn/v1")

    # 只在 API Key 或 Base URL 发生变化时更新
    if (
        existing_config.api_key != settings.api_key
        or existing_config.base_url != settings.base_url
    ):
        existing_config.api_key = settings.api_key
        existing_config.base_url = settings.base_url
        save_iflow_config(existing_config)


def set_auto_start(enabled: bool) -> bool:
    """设置开机自启动（跨平台）

    支持 Windows、macOS、Linux
    """
    return _set_auto_start(enabled)


def get_auto_start() -> bool:
    """检查是否已设置开机自启动（跨平台）"""
    return _get_auto_start()


def import_from_iflow_cli() -> Optional[IFlowConfig]:
    """从 iFlow CLI 导入配置"""
    try:
        return load_iflow_config()
    except Exception:
        return None
