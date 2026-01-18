"""OAuth token 自动刷新后台任务"""

import asyncio
import threading
from datetime import datetime, timedelta
from typing import Optional, Callable

from .oauth import IFlowOAuth
from .config import load_iflow_config, save_iflow_config, IFlowConfig


class OAuthTokenRefresher:
    """OAuth token 自动刷新器"""

    def __init__(
        self,
        check_interval: int = 3600,  # 每小时检查一次
        refresh_buffer: int = 300,  # 提前 5 分钟刷新
    ):
        """
        初始化 token 刷新器

        Args:
            check_interval: 检查间隔（秒）
            refresh_buffer: 提前刷新的缓冲时间（秒）
        """
        self.check_interval = check_interval
        self.refresh_buffer = refresh_buffer
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._on_refresh_callback: Optional[Callable] = None

    def set_refresh_callback(self, callback: Callable[[dict], None]):
        """
        设置刷新回调函数

        Args:
            callback: 回调函数，接收 token_data 参数
        """
        self._on_refresh_callback = callback

    def start(self):
        """启动 token 刷新后台任务"""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止 token 刷新后台任务"""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _run_loop(self):
        """运行刷新循环（在后台线程中）"""
        while not self._stop_event.is_set():
            try:
                # 检查是否需要刷新
                config = load_iflow_config()

                if (
                    config.auth_type == "oauth-iflow"
                    and config.oauth_refresh_token
                    and config.oauth_expires_at
                ):
                    # 检查是否需要刷新
                    oauth = IFlowOAuth()
                    if oauth.is_token_expired(
                        config.oauth_expires_at, self.refresh_buffer
                    ):
                        # 需要刷新 token
                        asyncio.run(self._refresh_token(config))

            except Exception:
                # 忽略错误，继续下一次检查
                pass

            # 等待下一次检查
            self._stop_event.wait(self.check_interval)

    async def _refresh_token(self, config: IFlowConfig):
        """
        刷新 token

        Args:
            config: 当前 iFlow 配置
        """
        try:
            oauth = IFlowOAuth()

            # 刷新 token
            if not config.oauth_refresh_token:
                return
            token_data = await oauth.refresh_token(config.oauth_refresh_token)

            # 更新配置
            config.oauth_access_token = token_data.get("access_token", "")
            if token_data.get("refresh_token"):
                config.oauth_refresh_token = token_data["refresh_token"]
            if token_data.get("expires_at"):
                config.oauth_expires_at = token_data["expires_at"]

            # 保存配置
            save_iflow_config(config)

            # 调用回调
            if self._on_refresh_callback:
                self._on_refresh_callback(token_data)

            await oauth.close()

        except Exception:
            # 刷新失败，记录错误
            try:
                oauth = IFlowOAuth()
                await oauth.close()
            except Exception:
                pass

    def is_running(self) -> bool:
        """
        检查是否正在运行

        Returns:
            True 表示正在运行
        """
        return self._running

    def should_refresh_now(self) -> bool:
        """
        检查是否需要立即刷新 token

        Returns:
            True 表示需要立即刷新
        """
        try:
            config = load_iflow_config()

            if (
                config.auth_type != "oauth-iflow"
                or not config.oauth_refresh_token
                or not config.oauth_expires_at
            ):
                return False

            oauth = IFlowOAuth()
            return oauth.is_token_expired(config.oauth_expires_at, self.refresh_buffer)

        except Exception:
            return False


# 全局刷新器实例
_global_refresher: Optional[OAuthTokenRefresher] = None


def get_global_refresher() -> OAuthTokenRefresher:
    """
    获取全局 token 刷新器实例

    Returns:
        OAuthTokenRefresher 实例
    """
    global _global_refresher

    if _global_refresher is None:
        _global_refresher = OAuthTokenRefresher()

    return _global_refresher


def start_global_refresher():
    """启动全局 token 刷新器"""
    refresher = get_global_refresher()
    refresher.start()


def stop_global_refresher():
    """停止全局 token 刷新器"""
    global _global_refresher

    if _global_refresher:
        _global_refresher.stop()
        _global_refresher = None
