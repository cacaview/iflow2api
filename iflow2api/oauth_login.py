"""OAuth 登录功能的独立模块"""

import webbrowser
import threading
import asyncio
from typing import Optional

from .oauth import IFlowOAuth
from .web_server import OAuthCallbackServer, find_available_port
from .config import load_iflow_config, save_iflow_config, IFlowConfig


class OAuthLoginHandler:
    """OAuth 登录处理器"""

    def __init__(self, add_log_callback):
        """
        初始化 OAuth 登录处理器

        Args:
            add_log_callback: 添加日志的回调函数
        """
        self.add_log = add_log_callback
        self._is_logging_in = False  # 防止重复登录

    def start_login(self):
        """启动 OAuth 登录流程"""
        if self._is_logging_in:
            self.add_log("OAuth 登录正在进行中，请勿重复点击")
            return

        self._is_logging_in = True
        self.add_log("正在启动 OAuth 登录流程...")

        # 在后台线程中执行 OAuth 流程
        def oauth_login_thread():
            try:
                # 1. 查找可用端口
                port = find_available_port(start_port=11451, max_attempts=50)
                if port is None:
                    self.add_log("无法找到可用端口")
                    self._is_logging_in = False
                    return

                # 2. 启动本地 OAuth 回调服务器
                server = OAuthCallbackServer(port=port)
                if not server.start():
                    self.add_log("无法启动 OAuth 回调服务器")
                    self._is_logging_in = False
                    return

                self.add_log(f"OAuth 回调服务器已启动: {server.get_callback_url()}")

                # 3. 打开浏览器访问 OAuth 授权页面
                oauth = IFlowOAuth()
                auth_url = oauth.get_auth_url(redirect_uri=server.get_callback_url())
                webbrowser.open(auth_url)
                self.add_log("已打开浏览器，请完成授权...")

                # 4. 等待回调
                code, error = server.wait_for_callback(timeout=60)
                server.stop()

                if error:
                    self.add_log(f"OAuth 授权失败: {error}")
                    self._is_logging_in = False
                    return

                if not code:
                    self.add_log("OAuth 授权失败: 未收到授权码")
                    self._is_logging_in = False
                    return

                self.add_log("收到授权码，正在获取 token...")

                # 5. 获取 token
                async def get_token_async():
                    try:
                        token_data = await oauth.get_token(
                            code, redirect_uri=server.get_callback_url()
                        )

                        # 6. 获取用户信息和 API Key
                        self.add_log("正在获取用户信息...")
                        user_info = await oauth.get_user_info(
                            token_data.get("access_token", "")
                        )

                        api_key = user_info.get("apiKey")
                        if not api_key:
                            raise ValueError("未能获取 API Key")

                        # 保存到 ~/.iflow/settings.json
                        # 尝试加载现有配置
                        try:
                            existing_config = load_iflow_config()
                        except (FileNotFoundError, ValueError):
                            existing_config = IFlowConfig(
                                api_key=api_key,
                                base_url="https://apis.iflow.cn/v1",
                                auth_type="oauth-iflow",
                            )

                        # 更新配置
                        existing_config.api_key = api_key
                        existing_config.auth_type = "oauth-iflow"
                        existing_config.oauth_access_token = token_data.get(
                            "access_token", ""
                        )
                        existing_config.oauth_refresh_token = token_data.get(
                            "refresh_token", ""
                        )
                        if token_data.get("expires_at"):
                            existing_config.oauth_expires_at = token_data["expires_at"]

                        save_iflow_config(existing_config)

                        self.add_log(
                            f"登录成功！用户: {user_info.get('username', user_info.get('phone', 'Unknown'))}"
                        )
                        self.add_log(f"API Key: {api_key[:10]}...{api_key[-4:]}")

                        await oauth.close()
                    except Exception as ex:
                        self.add_log(f"获取 token 失败: {str(ex)}")
                        await oauth.close()
                    finally:
                        self._is_logging_in = False

                asyncio.run(get_token_async())

            except Exception as ex:
                self.add_log(f"OAuth 登录异常: {str(ex)}")
                self._is_logging_in = False

        thread = threading.Thread(target=oauth_login_thread, daemon=True)
        thread.start()
