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
    minimize_to_tray: bool = True  # 关闭时最小化到托盘
    auto_run_server: bool = False  # 启动时自动运行服务


def get_config_dir() -> Path:
    """获取应用配置目录"""
    return Path.home() / ".iflow2api"


def get_config_path() -> Path:
    """获取应用配置文件路径"""
    return get_config_dir() / "config.json"


def load_settings() -> AppSettings:
    """加载配置"""
    settings = AppSettings()

    # 从 ~/.iflow/settings.json 加载 iFlow 配置
    try:
        iflow_config = load_iflow_config()
        settings.api_key = iflow_config.api_key
        settings.base_url = iflow_config.base_url
        settings.auth_type = iflow_config.auth_type or "api-key"
        settings.oauth_access_token = iflow_config.oauth_access_token or ""
        settings.oauth_refresh_token = iflow_config.oauth_refresh_token or ""
        if iflow_config.oauth_expires_at:
            settings.oauth_expires_at = iflow_config.oauth_expires_at.isoformat()
    except Exception:
        pass

    # 从 ~/.iflow2api/config.json 加载应用设置
    app_config_path = get_config_path()
    if app_config_path.exists():
        try:
            with open(app_config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 只加载应用相关的设置
                if "host" in data:
                    settings.host = data["host"]
                if "port" in data:
                    settings.port = data["port"]
                if "auto_start" in data:
                    settings.auto_start = data["auto_start"]
                if "start_minimized" in data:
                    settings.start_minimized = data["start_minimized"]
                if "minimize_to_tray" in data:
                    settings.minimize_to_tray = data["minimize_to_tray"]
                if "auto_run_server" in data:
                    settings.auto_run_server = data["auto_run_server"]
        except Exception:
            pass

    return settings


def save_settings(settings: AppSettings) -> None:
    """
    保存配置

    - 应用设置保存到 ~/.iflow2api/config.json
    - iFlow 配置保存到 ~/.iflow/settings.json
    """
    # 1. 保存应用设置到 ~/.iflow2api/config.json
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    app_data = {
        "host": settings.host,
        "port": settings.port,
        "auto_start": settings.auto_start,
        "start_minimized": settings.start_minimized,
        "minimize_to_tray": settings.minimize_to_tray,
        "auto_run_server": settings.auto_run_server,
    }

    config_path = get_config_path()
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(app_data, f, indent=2, ensure_ascii=False)

    # 2. 如果 API Key 或 Base URL 发生变化，更新 ~/.iflow/settings.json
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
