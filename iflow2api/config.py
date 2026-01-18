"""iFlow 配置读取器 - 从 ~/.iflow/settings.json 读取认证信息"""

import json
import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime


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
            print(f"[警告] 当前使用 openai-compatible 模式，部分模型可能不可用")
        elif auth_type:
            print(f"[警告] 未知的认证类型: {auth_type}")

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
    )


def check_iflow_login() -> bool:
    """检查 iFlow 是否已登录"""
    try:
        config = load_iflow_config()
        return bool(config.api_key)
    except (FileNotFoundError, ValueError):
        return False


def save_iflow_config(config: IFlowConfig) -> None:
    """
    保存 iFlow 配置到 ~/.iflow/settings.json

    Args:
        config: IFlowConfig 配置对象
    """
    config_path = get_iflow_config_path()
    config_dir = config_path.parent
    config_dir.mkdir(parents=True, exist_ok=True)

    # 转换为字典
    data = {
        "apiKey": config.api_key,
        "baseUrl": config.base_url,
    }

    # 添加可选字段
    if config.model_name:
        data["modelName"] = config.model_name
    if config.cna:
        data["cna"] = config.cna
    if config.auth_type:
        data["selectedAuthType"] = config.auth_type
    if config.oauth_access_token:
        data["oauth_access_token"] = config.oauth_access_token
    if config.oauth_refresh_token:
        data["oauth_refresh_token"] = config.oauth_refresh_token
    if config.oauth_expires_at:
        data["oauth_expires_at"] = config.oauth_expires_at.isoformat()

    # 保存到文件
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
