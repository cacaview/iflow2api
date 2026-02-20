"""服务管理 - 在后台线程运行 uvicorn"""

import asyncio
import socket
import threading
import time
from enum import Enum
from typing import Callable, Optional

import uvicorn

from .settings import AppSettings


class ServerState(Enum):
    """服务状态"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


def is_port_available(host: str, port: int) -> bool:
    """检查端口是否可用"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host if host != "0.0.0.0" else "127.0.0.1", port))
            return True
    except OSError:
        return False


class ServerManager:
    """服务管理器"""

    def __init__(self, on_state_change: Optional[Callable[[ServerState, str], None]] = None):
        self._state = ServerState.STOPPED
        self._thread: Optional[threading.Thread] = None
        self._server: Optional[uvicorn.Server] = None
        self._on_state_change = on_state_change
        self._error_message = ""
        self._settings: Optional[AppSettings] = None

    @property
    def state(self) -> ServerState:
        return self._state

    @property
    def error_message(self) -> str:
        return self._error_message

    def _set_state(self, state: ServerState, message: str = ""):
        self._state = state
        self._error_message = message
        if self._on_state_change:
            try:
                self._on_state_change(state, message)
            except Exception:
                pass  # 忽略回调错误，避免崩溃

    def start(self, settings: AppSettings) -> bool:
        """启动服务"""
        if self._state in (ServerState.RUNNING, ServerState.STARTING):
            return False

        # 注意：不再强制检查 api_key，允许在没有配置的情况下启动服务
        # 这样用户可以通过 webui 进行 OAuth 登录配置

        # 检查端口是否可用
        if not is_port_available(settings.host, settings.port):
            self._set_state(ServerState.ERROR, f"端口 {settings.port} 已被占用")
            return False

        self._settings = settings
        self._set_state(ServerState.STARTING)

        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> bool:
        """停止服务"""
        if self._state not in (ServerState.RUNNING, ServerState.STARTING):
            return False

        self._set_state(ServerState.STOPPING)

        if self._server:
            self._server.should_exit = True

        # 等待线程结束
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        self._set_state(ServerState.STOPPED)
        return True

    def _run_server(self):
        """在线程中运行服务"""
        try:
            # 动态设置配置
            from . import config as config_module
            from .config import IFlowConfig

            # 创建自定义配置
            custom_config = IFlowConfig(
                api_key=self._settings.api_key,
                base_url=self._settings.base_url,
            )

            # 替换 load_iflow_config 函数
            def patched_load():
                return custom_config

            config_module.load_iflow_config = patched_load

            # 重置全局代理实例
            from . import app as app_module
            app_module._proxy = None
            app_module._config = None

            # 直接导入 app 对象，避免打包后字符串导入失败
            from .app import app

            # 配置 uvicorn - 直接传入 app 对象而非字符串
            config = uvicorn.Config(
                app,
                host=self._settings.host,
                port=self._settings.port,
                log_level="info",
                access_log=True,
            )

            self._server = uvicorn.Server(config)
            self._set_state(ServerState.RUNNING)

            # 运行服务
            asyncio.run(self._server.serve())

        except OSError as e:
            # 端口绑定错误
            if "address already in use" in str(e).lower() or "通常每个套接字地址" in str(e):
                self._set_state(ServerState.ERROR, f"端口 {self._settings.port} 已被占用")
            else:
                self._set_state(ServerState.ERROR, str(e))
        except Exception as e:
            self._set_state(ServerState.ERROR, str(e))
        finally:
            self._server = None
            if self._state != ServerState.ERROR:
                self._set_state(ServerState.STOPPED)
