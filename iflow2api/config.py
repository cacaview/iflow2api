"""iFlow 配置读取器 - 从 ~/.iflow/settings.json 读取认证信息"""

import json
import logging
import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime

logger = logging.getLogger("iflow2api")


class IFlowConfig(BaseModel):
    """iFlow 配置"""

    api_key: str
    base_url: str = "https://apis.iflow.cn/v1"
    model_name: Optional[str] = None
    cna: Optional[str] = None
    installation_id: Optional[str] = None
    # OAuth 相关字段
    auth_type: Optional[str] = Field(
        default=None, description="认证类型: oauth-iflow, api-key, openai-compatible"
    )
    oauth_access_token: Optional[str] = Field(
        default=None, description="OAuth 访问令牌"
    )
    oauth_refresh_token: Optional[str] = Field(
        default=None, description="OAuth 刷新令牌"
    )
    oauth_expires_at: Optional[datetime] = Field(
        default=None, description="OAuth token 过期时间"
    )
    # apiKey 过期时间（与 oauth_expires_at 相同，用于清晰语义）
    api_key_expires_at: Optional[datetime] = Field(
        default=None, description="apiKey 过期时间（OAuth 模式下与 token 同步）"
    )


def get_iflow_config_path() -> Path:
    """获取 iFlow 配置文件路径"""
    # Windows: C:\Users\<user>\.iflow\settings.json
    # Linux/Mac: ~/.iflow/settings.json
    home = Path.home()
    return home / ".iflow" / "settings.json"


def get_installation_id_path() -> Path:
    """获取 installation_id 文件路径"""
    home = Path.home()
    return home / ".iflow" / "installation_id"


def load_iflow_config() -> IFlowConfig:
    """
    从 iFlow CLI 配置文件加载认证信息

    Returns:
        IFlowConfig: 包含 API Key 和 Base URL 的配置对象

    Raises:
        FileNotFoundError: 配置文件不存在
        ValueError: 配置文件格式错误或缺少必要字段
    """
    config_path = get_iflow_config_path()

    if not config_path.exists():
        raise FileNotFoundError(
            f"iFlow 配置文件不存在: {config_path}\n请先运行 iflow 命令并完成登录"
        )

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"iFlow 配置文件格式错误: {e}")

    # 检查认证类型
    auth_type = data.get("selectedAuthType", "")
    if auth_type not in ("oauth-iflow", "api-key"):
        # 也支持 openai-compatible 模式，但会给出警告
        if auth_type == "openai-compatible":
            logger.warning("当前使用 openai-compatible 模式，部分模型可能不可用")
        elif auth_type:
            logger.warning("未知的认证类型: %s", auth_type)

    # 获取 API Key
    api_key = data.get("apiKey") or data.get("searchApiKey")
    if not api_key:
        raise ValueError("iFlow 配置中缺少 API Key\n请先运行 iflow 命令并完成登录")

    # 获取 Base URL
    base_url = data.get("baseUrl", "https://apis.iflow.cn/v1")

    # 获取其他可选配置
    model_name = data.get("modelName")
    cna = data.get("cna")

    # 解析 OAuth token 过期时间
    oauth_expires_at = None
    expires_at_str = data.get("oauth_expires_at")
    if expires_at_str:
        try:
            oauth_expires_at = datetime.fromisoformat(expires_at_str)
        except (ValueError, TypeError):
            pass

    # 尝试读取 installation_id
    installation_id = None
    installation_id_path = get_installation_id_path()
    if installation_id_path.exists():
        try:
            installation_id = installation_id_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass

    # apiKey 过期时间（OAuth 模式下与 oauth_expires_at 相同）
    api_key_expires_at = oauth_expires_at

    return IFlowConfig(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        cna=cna,
        installation_id=installation_id,
        auth_type=auth_type,
        oauth_access_token=data.get("oauth_access_token"),
        oauth_refresh_token=data.get("oauth_refresh_token"),
        oauth_expires_at=oauth_expires_at,
        api_key_expires_at=api_key_expires_at,
    )


def check_iflow_login() -> bool:
    """检查 iFlow 是否已登录
    
    检查顺序：
    1. 先检查 ~/.iflow2api/config.json（应用主配置）
    2. 再检查 ~/.iflow/settings.json（iFlow CLI 配置）
    """
    # 首先检查应用主配置
    from pathlib import Path
    app_config_path = Path.home() / ".iflow2api" / "config.json"
    if app_config_path.exists():
        try:
            import json
            with open(app_config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("api_key"):
                return True
        except Exception:
            pass
    
    # 再检查 iFlow CLI 配置
    try:
        config = load_iflow_config()
        return bool(config.api_key)
    except (FileNotFoundError, ValueError):
        return False


def save_iflow_config(config: IFlowConfig) -> None:
    """
    保存 iFlow 配置到 ~/.iflow/settings.json

    仅更新已知字段，保留文件中原有的未知字段（M-03 修复）

    Args:
        config: IFlowConfig 配置对象
    """
    config_path = get_iflow_config_path()
    config_dir = config_path.parent
    config_dir.mkdir(parents=True, exist_ok=True)

    # 先读取现有数据，保留未知字段（M-03 修复）
    existing_data: dict = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing_data = {}

    # 仅覆盖已知字段
    existing_data["apiKey"] = config.api_key
    existing_data["baseUrl"] = config.base_url

    if config.model_name is not None:
        existing_data["modelName"] = config.model_name
    if config.cna is not None:
        existing_data["cna"] = config.cna
    if config.auth_type is not None:
        existing_data["selectedAuthType"] = config.auth_type
    if config.oauth_access_token is not None:
        existing_data["oauth_access_token"] = config.oauth_access_token
    if config.oauth_refresh_token is not None:
        existing_data["oauth_refresh_token"] = config.oauth_refresh_token
    if config.oauth_expires_at is not None:
        existing_data["oauth_expires_at"] = config.oauth_expires_at.isoformat()
    if config.api_key_expires_at is not None:
        existing_data["api_key_expires_at"] = config.api_key_expires_at.isoformat()

    # 保存到文件
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, indent=2, ensure_ascii=False)
