"""Web 管理界面路由"""

import asyncio
import platform
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from .auth import get_auth_manager
from .websocket import get_connection_manager


# 创建路由器
admin_router = APIRouter(prefix="/admin", tags=["Admin"])

# HTTP Bearer 认证方案
security = HTTPBearer(auto_error=False)


# 请求/响应模型
class LoginRequest(BaseModel):
    """登录请求"""
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    """修改密码请求"""
    old_password: str
    new_password: str


class CreateUserRequest(BaseModel):
    """创建用户请求"""
    username: str
    password: str


class SettingsUpdate(BaseModel):
    """设置更新请求"""
    host: Optional[str] = None
    port: Optional[int] = None
    auto_start: Optional[bool] = None
    start_minimized: Optional[bool] = None
    close_action: Optional[str] = None  # 关闭按钮行为: exit, minimize_to_tray, minimize_to_taskbar
    auto_run_server: Optional[bool] = None
    theme_mode: Optional[str] = None
    preserve_reasoning_content: Optional[bool] = None
    api_concurrency: Optional[int] = None
    language: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    custom_api_key: Optional[str] = None
    custom_auth_header: Optional[str] = None


class OAuthCallbackRequest(BaseModel):
    """OAuth 回调请求"""
    code: str
    state: Optional[str] = None


# 认证依赖
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """获取当前认证用户"""
    if credentials is None:
        raise HTTPException(status_code=401, detail="未提供认证令牌")
    
    auth_manager = get_auth_manager()
    username = auth_manager.verify_token(credentials.credentials)
    
    if username is None:
        raise HTTPException(status_code=401, detail="无效或过期的令牌")
    
    return username


# ==================== 认证相关 ====================

@admin_router.post("/login")
async def login(request: LoginRequest) -> dict[str, Any]:
    """用户登录"""
    auth_manager = get_auth_manager()
    
    # 如果没有用户，创建第一个用户
    if not auth_manager.has_users():
        auth_manager.create_user(request.username, request.password)
        token = auth_manager.authenticate(request.username, request.password)
        return {
            "success": True,
            "token": token,
            "message": "首次登录，已创建管理员账户",
            "is_first_login": True,
        }
    
    token = auth_manager.authenticate(request.username, request.password)
    if token is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    return {
        "success": True,
        "token": token,
        "message": "登录成功",
        "is_first_login": False,
    }


@admin_router.post("/logout")
async def logout(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict[str, Any]:
    """用户登出"""
    if credentials:
        auth_manager = get_auth_manager()
        auth_manager.logout(credentials.credentials)
    
    return {"success": True, "message": "已登出"}


@admin_router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    username: str = Depends(get_current_user),
) -> dict[str, Any]:
    """修改密码"""
    auth_manager = get_auth_manager()
    success = auth_manager.change_password(username, request.old_password, request.new_password)
    
    if not success:
        raise HTTPException(status_code=400, detail="原密码错误")
    
    return {"success": True, "message": "密码已修改"}


@admin_router.get("/check-setup")
async def check_setup() -> dict[str, Any]:
    """检查是否需要初始化设置"""
    auth_manager = get_auth_manager()
    return {
        "needs_setup": not auth_manager.has_users(),
        "has_users": auth_manager.has_users(),
    }


# ==================== 用户管理 ====================

@admin_router.get("/users")
async def get_users(username: str = Depends(get_current_user)) -> list[dict]:
    """获取用户列表"""
    auth_manager = get_auth_manager()
    return auth_manager.get_users()


@admin_router.post("/users")
async def create_user(
    request: CreateUserRequest,
    username: str = Depends(get_current_user),
) -> dict[str, Any]:
    """创建新用户"""
    auth_manager = get_auth_manager()
    success = auth_manager.create_user(request.username, request.password)
    
    if not success:
        raise HTTPException(status_code=400, detail="用户名已存在")
    
    return {"success": True, "message": "用户已创建"}


@admin_router.delete("/users/{target_username}")
async def delete_user(
    target_username: str,
    username: str = Depends(get_current_user),
) -> dict[str, Any]:
    """删除用户"""
    if target_username == username:
        raise HTTPException(status_code=400, detail="不能删除自己")
    
    auth_manager = get_auth_manager()
    success = auth_manager.delete_user(target_username)
    
    if not success:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    return {"success": True, "message": "用户已删除"}


# ==================== 系统状态 ====================

def _check_service_health(port: int, host: str = "127.0.0.1") -> tuple[bool, str]:
    """
    检查服务健康状态（L-04 修复：改用非阻塞 socket 替代同步 http.client，
    避免在 asyncio event loop 中阻塞）

    Returns:
        (is_healthy, error_message)
    """
    import socket

    # 只做端口连通性检查（纯 socket，非阻塞）
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex((host, port))
            if result != 0:
                return False, f"端口 {port} 未监听"
            return True, ""
    except Exception as e:
        return False, f"端口检查失败: {str(e)}"


@admin_router.get("/status")
async def get_status(username: str = Depends(get_current_user)) -> dict[str, Any]:
    """获取系统状态"""
    from ..settings import load_settings
    
    # 获取服务器管理器状态
    server_manager = _get_server_manager()
    manager_state = server_manager.state.value if server_manager else "stopped"
    manager_error = server_manager.error_message if server_manager else ""
    
    # 获取配置的端口
    settings = load_settings()
    configured_port = settings.port
    
    # 实际检查服务健康状态
    is_healthy, health_error = _check_service_health(configured_port)
    
    # 确定最终状态
    # 如果服务健康，则显示运行中，否则使用管理器状态
    if is_healthy:
        actual_state = "running"
        actual_error = ""
    else:
        actual_state = manager_state if manager_state != "running" else "stopped"
        actual_error = health_error or manager_error
    
    # 获取系统信息
    system_info = {
        "platform": platform.system(),
        "platform_version": platform.version(),
        "python_version": sys.version,
        "architecture": platform.machine(),
    }
    
    # 获取进程信息
    process_info = {
        "start_time": _get_process_start_time(),
        "uptime": time.time() - _process_start_time,
    }
    
    # 获取连接管理器状态
    connection_manager = get_connection_manager()
    
    return {
        "server": {
            "state": actual_state,
            "error_message": actual_error,
            "manager_state": manager_state,  # 保留管理器状态供调试
            "configured_port": configured_port,
        },
        "system": system_info,
        "process": process_info,
        "connections": {
            "websocket_count": connection_manager.connection_count,
        },
    }


@admin_router.get("/metrics")
async def get_metrics(username: str = Depends(get_current_user)) -> dict[str, Any]:
    """获取性能指标"""
    proxy_stats = {}
    
    # 获取代理统计
    try:
        from ..app import get_proxy
        proxy = get_proxy()
        if proxy and hasattr(proxy, 'get_stats'):
            proxy_stats = proxy.get_stats()
    except Exception as e:
        proxy_stats = {"error": str(e)}
    
    return {
        "proxy": proxy_stats,
        "timestamp": datetime.now().isoformat(),
    }


# ==================== 配置管理 ====================

@admin_router.get("/settings")
async def get_settings(username: str = Depends(get_current_user)) -> dict[str, Any]:
    """获取应用设置"""
    from ..settings import load_settings
    
    settings = load_settings()
    return {
        "host": settings.host,
        "port": settings.port,
        "auto_start": settings.auto_start,
        "start_minimized": settings.start_minimized,
        "close_action": settings.close_action,
        "auto_run_server": settings.auto_run_server,
        "theme_mode": settings.theme_mode,
        "preserve_reasoning_content": settings.preserve_reasoning_content,
        "api_concurrency": settings.api_concurrency,
        "language": settings.language,
        "api_key": settings.api_key,
        "base_url": settings.base_url,
        "custom_api_key": settings.custom_api_key,
        "custom_auth_header": settings.custom_auth_header,
        # 不返回 OAuth 敏感信息
    }


@admin_router.put("/settings")
async def update_settings(
    request: SettingsUpdate,
    username: str = Depends(get_current_user),
) -> dict[str, Any]:
    """更新应用设置"""
    from ..settings import load_settings, save_settings
    
    settings = load_settings()
    
    # 更新设置
    if request.host is not None:
        settings.host = request.host
    if request.port is not None:
        settings.port = request.port
    if request.auto_start is not None:
        settings.auto_start = request.auto_start
        # 同时设置系统自启动
        from ..settings import set_auto_start
        set_auto_start(request.auto_start)
    if request.start_minimized is not None:
        settings.start_minimized = request.start_minimized
    if request.close_action is not None:
        settings.close_action = request.close_action
    if request.auto_run_server is not None:
        settings.auto_run_server = request.auto_run_server
    if request.theme_mode is not None:
        settings.theme_mode = request.theme_mode
    if request.preserve_reasoning_content is not None:
        settings.preserve_reasoning_content = request.preserve_reasoning_content
    if request.api_concurrency is not None:
        settings.api_concurrency = request.api_concurrency
    if request.language is not None:
        settings.language = request.language
    if request.api_key is not None:
        settings.api_key = request.api_key
    if request.base_url is not None:
        settings.base_url = request.base_url
    if request.custom_api_key is not None:
        settings.custom_api_key = request.custom_api_key
    if request.custom_auth_header is not None:
        settings.custom_auth_header = request.custom_auth_header
    
    save_settings(settings)
    
    # 广播设置变更
    connection_manager = get_connection_manager()
    await connection_manager.broadcast({
        "type": "settings_updated",
        "timestamp": datetime.now().isoformat(),
    })
    
    return {"success": True, "message": "设置已保存"}


# ==================== iFlow 配置 ====================

@admin_router.post("/import-from-cli")
async def import_from_cli(
    username: str = Depends(get_current_user),
) -> dict[str, Any]:
    """从 iFlow CLI 导入配置"""
    from ..settings import import_from_iflow_cli
    
    config = import_from_iflow_cli()
    if config:
        return {
            "success": True,
            "message": "已从 iFlow CLI 导入配置",
            "api_key": config.api_key,
            "base_url": config.base_url,
        }
    else:
        raise HTTPException(
            status_code=400,
            detail="无法导入 iFlow CLI 配置，请确保已运行 iflow 并完成登录"
        )


@admin_router.get("/oauth/url")
async def get_oauth_url(
    request: Request,
    username: str = Depends(get_current_user),
) -> dict[str, Any]:
    """获取 iFlow OAuth 登录 URL"""
    from ..oauth import IFlowOAuth
    
    oauth = IFlowOAuth()
    # 从请求中获取实际端口
    port = request.url.port or 28000
    redirect_uri = f"http://localhost:{port}/admin/oauth/callback"
    auth_url = oauth.get_auth_url(redirect_uri=redirect_uri)
    
    return {
        "success": True,
        "auth_url": auth_url,
        "redirect_uri": redirect_uri,
    }


@admin_router.get("/oauth/callback")
async def oauth_callback_get(code: str, state: Optional[str] = None):
    """处理 OAuth 回调（GET 请求 - 从 iFlow 重定向回来）
    
    返回一个 HTML 页面，通过 postMessage 将授权码发送回父窗口
    """
    from fastapi.responses import HTMLResponse
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>OAuth 回调</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background: #f5f5f5;
            }}
            .container {{
                text-align: center;
                padding: 40px;
                background: white;
                border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }}
            .spinner {{
                width: 40px;
                height: 40px;
                border: 3px solid #f3f3f3;
                border-top: 3px solid #3498db;
                border-radius: 50%;
                animation: spin 1s linear infinite;
                margin: 0 auto 20px;
            }}
            @keyframes spin {{
                0% {{ transform: rotate(0deg); }}
                100% {{ transform: rotate(360deg); }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="spinner"></div>
            <p>正在处理登录...</p>
        </div>
        <script>
            // 将授权码发送回父窗口
            if (window.opener) {{
                window.opener.postMessage({{
                    type: 'oauth_callback',
                    code: '{code}',
                    state: '{state or ''}'
                }}, '*');
                // 关闭当前窗口
                setTimeout(function() {{
                    window.close();
                }}, 1000);
            }} else {{
                // 如果没有 opener，显示错误
                document.querySelector('.container').innerHTML =
                    '<p style="color: red;">错误：无法与父窗口通信</p>' +
                    '<p>请手动关闭此窗口</p>';
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@admin_router.post("/oauth/callback")
async def oauth_callback(
    callback_request: OAuthCallbackRequest,
    fastapi_request: Request,
    username: str = Depends(get_current_user),
) -> dict[str, Any]:
    """处理 OAuth 回调（POST 请求 - 从前端发送）"""
    from ..oauth import IFlowOAuth
    from ..settings import load_settings, save_settings
    
    oauth = IFlowOAuth()
    # 从请求中获取实际端口
    port = fastapi_request.url.port or 28000
    redirect_uri = f"http://localhost:{port}/admin/oauth/callback"
    
    try:
        # 使用授权码获取 token
        token_data = await oauth.get_token(callback_request.code, redirect_uri=redirect_uri)
        access_token = token_data.get("access_token")
        
        if not access_token:
            raise HTTPException(status_code=400, detail="OAuth 响应缺少 access_token")
        
        # 获取用户信息（包含 API Key）
        user_info = await oauth.get_user_info(access_token)
        api_key = user_info.get("apiKey")
        
        if not api_key:
            raise HTTPException(status_code=400, detail="无法获取 API Key")
        
        # 保存配置
        settings = load_settings()
        settings.api_key = api_key
        settings.auth_type = "oauth-iflow"
        settings.oauth_access_token = access_token
        if token_data.get("refresh_token"):
            settings.oauth_refresh_token = token_data["refresh_token"]
        if token_data.get("expires_at"):
            settings.oauth_expires_at = token_data["expires_at"].isoformat()
        save_settings(settings)
        
        return {
            "success": True,
            "message": "登录成功！配置已自动更新",
            "api_key": api_key,
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth 登录失败: {str(e)}")


# ==================== 服务器控制 ====================

@admin_router.post("/server/start")
async def start_server(username: str = Depends(get_current_user)) -> dict[str, Any]:
    """启动服务器"""
    from ..settings import load_settings
    
    server_manager = _get_server_manager()
    if server_manager is None:
        raise HTTPException(status_code=500, detail="服务器管理器未初始化")
    
    settings = load_settings()
    success = server_manager.start(settings)
    
    if not success:
        raise HTTPException(status_code=400, detail=server_manager.error_message or "启动失败")
    
    return {"success": True, "message": "服务器已启动"}


@admin_router.post("/server/stop")
async def stop_server(username: str = Depends(get_current_user)) -> dict[str, Any]:
    """停止服务器"""
    server_manager = _get_server_manager()
    if server_manager is None:
        raise HTTPException(status_code=500, detail="服务器管理器未初始化")
    
    success = server_manager.stop()
    
    if not success:
        raise HTTPException(status_code=400, detail="停止失败")
    
    return {"success": True, "message": "服务器已停止"}


@admin_router.post("/server/restart")
async def restart_server(username: str = Depends(get_current_user)) -> dict[str, Any]:
    """重启服务器"""
    from ..settings import load_settings
    
    server_manager = _get_server_manager()
    if server_manager is None:
        raise HTTPException(status_code=500, detail="服务器管理器未初始化")
    
    # 先停止
    server_manager.stop()
    
    # 等待停止完成
    await asyncio.sleep(1)
    
    # 重新启动
    settings = load_settings()
    success = server_manager.start(settings)
    
    if not success:
        raise HTTPException(status_code=400, detail=server_manager.error_message or "重启失败")
    
    return {"success": True, "message": "服务器已重启"}


# ==================== 日志查看 ====================

@admin_router.get("/logs")
async def get_logs(
    lines: int = 100,
    username: str = Depends(get_current_user),
) -> dict[str, Any]:
    """获取日志"""
    log_path = Path.home() / ".iflow2api" / "logs" / "app.log"
    
    if not log_path.exists():
        return {"logs": [], "message": "日志文件不存在"}
    
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
        
        return {
            "logs": [line.strip() for line in recent_lines],
            "total_lines": len(all_lines),
        }
    except Exception as e:
        return {"logs": [], "error": str(e)}


# ==================== WebSocket ====================

@admin_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 连接端点（M-10 修复：连接建立时即验证 Token）"""
    # 在 HTTP Upgrade 阶段验证 token（来自查询参数）
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    auth_manager = get_auth_manager()
    username = auth_manager.verify_token(token)
    if not username:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    connection_manager = get_connection_manager()
    await connection_manager.connect(websocket)

    try:
        while True:
            data = await websocket.receive_json()

            # 处理心跳
            if data.get("type") == "ping":
                await connection_manager.send_personal(websocket, {
                    "type": "pong",
                    "timestamp": datetime.now().isoformat(),
                })
            # 支持旧版客户端通过消息中的 auth 命令认证（向后兼容）
            elif data.get("type") == "auth":
                await connection_manager.send_personal(websocket, {
                    "type": "auth_success",
                    "username": username,
                })
    except WebSocketDisconnect:
        await connection_manager.disconnect(websocket)
    except Exception:
        await connection_manager.disconnect(websocket)


# ==================== 辅助函数 ====================

# 进程启动时间
_process_start_time = time.time()


def _get_process_start_time() -> str:
    """获取进程启动时间"""
    return datetime.fromtimestamp(_process_start_time).isoformat()


# 服务器管理器引用
_server_manager: Optional[Any] = None


def set_server_manager(manager: Any) -> None:
    """设置服务器管理器引用"""
    global _server_manager
    _server_manager = manager


def _get_server_manager() -> Optional[Any]:
    """获取服务器管理器引用"""
    return _server_manager
