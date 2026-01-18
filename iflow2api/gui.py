"""Flet GUI 应用"""

import flet as ft
from datetime import datetime
from typing import Optional
import threading

from .settings import (
    AppSettings,
    load_settings,
    save_settings,
    set_auto_start,
    get_auto_start,
    import_from_iflow_cli,
)
from .server import ServerManager, ServerState
import webbrowser
import asyncio


class IFlow2ApiApp:
    """iflow2api GUI 应用"""

    def __init__(self, page: ft.Page):
        self.page = page
        self.settings = load_settings()

        # 设置 pubsub 用于线程安全的 UI 更新
        self.page.pubsub.subscribe(self._on_pubsub_message)

        self.server = ServerManager(
            on_state_change=self._on_server_state_change_threadsafe
        )

        # UI 组件
        self.status_icon: Optional[ft.Icon] = None
        self.status_text: Optional[ft.Text] = None
        self.host_field: Optional[ft.TextField] = None
        self.port_field: Optional[ft.TextField] = None
        self.api_key_field: Optional[ft.TextField] = None
        self.base_url_field: Optional[ft.TextField] = None
        self.auto_start_checkbox: Optional[ft.Checkbox] = None
        self.start_minimized_checkbox: Optional[ft.Checkbox] = None
        self.auto_run_checkbox: Optional[ft.Checkbox] = None
        self.start_btn: Optional[ft.ElevatedButton] = None
        self.stop_btn: Optional[ft.ElevatedButton] = None
        self.log_list: Optional[ft.ListView] = None

        self._setup_page()
        self._build_ui()

        # 启动时自动运行服务
        if self.settings.auto_run_server:
            self._start_server(None)

        # 启动时最小化
        if self.settings.start_minimized:
            self.page.window.minimized = True

    def _setup_page(self):
        """设置页面"""
        self.page.title = "iflow2api"
        self.page.window.width = 500
        self.page.window.height = 980
        self.page.window.resizable = True
        self.page.window.min_width = 400
        self.page.window.min_height = 500
        self.page.padding = 20

        # 窗口关闭事件
        self.page.window.on_event = self._on_window_event

    def _on_window_event(self, e):
        """窗口事件处理"""
        if e.data == "close":
            # 停止服务并退出
            self.server.stop()
            self.page.window.destroy()

    def _build_ui(self):
        """构建 UI"""
        # 状态栏
        self.status_icon = ft.Icon(ft.Icons.CIRCLE, color=ft.Colors.GREY, size=16)
        self.status_text = ft.Text("服务未运行", size=14)

        status_row = ft.Container(
            content=ft.Row([self.status_icon, self.status_text]),
            padding=10,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border_radius=8,
        )

        # 服务器配置
        self.host_field = ft.TextField(
            label="监听地址",
            value=self.settings.host,
            hint_text="0.0.0.0",
            expand=True,
        )
        self.port_field = ft.TextField(
            label="监听端口",
            value=str(self.settings.port),
            hint_text="8000",
            keyboard_type=ft.KeyboardType.NUMBER,
            width=120,
        )

        server_config = ft.Container(
            content=ft.Column(
                [
                    ft.Text("服务器配置", weight=ft.FontWeight.BOLD),
                    ft.Row([self.host_field, self.port_field]),
                ]
            ),
            padding=15,
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=8,
        )

        # iFlow 配置
        self.api_key_field = ft.TextField(
            label="API Key",
            value=self.settings.api_key,
            password=True,
            can_reveal_password=True,
            expand=True,
        )
        self.base_url_field = ft.TextField(
            label="Base URL",
            value=self.settings.base_url,
            hint_text="https://apis.iflow.cn/v1",
        )

        import_btn = ft.TextButton(
            "从 iFlow CLI 导入配置",
            icon=ft.Icons.DOWNLOAD,
            on_click=self._import_from_cli,
        )

        oauth_login_btn = ft.ElevatedButton(
            "Login with iFlow",
            icon=ft.Icons.LOGIN,
            on_click=self._login_with_iflow_oauth,
            style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE),
        )

        iflow_config = ft.Container(
            content=ft.Column(
                [
                    ft.Text("iFlow 配置", weight=ft.FontWeight.BOLD),
                    self.api_key_field,
                    self.base_url_field,
                    ft.Row(
                        [import_btn, oauth_login_btn],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                ]
            ),
            padding=15,
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=8,
        )

        # 应用设置
        self.auto_start_checkbox = ft.Checkbox(
            label="开机自启动",
            value=get_auto_start(),
            on_change=self._on_auto_start_change,
        )
        self.start_minimized_checkbox = ft.Checkbox(
            label="启动时最小化",
            value=self.settings.start_minimized,
        )
        self.auto_run_checkbox = ft.Checkbox(
            label="启动时自动运行服务",
            value=self.settings.auto_run_server,
        )

        app_settings = ft.Container(
            content=ft.Column(
                [
                    ft.Text("应用设置", weight=ft.FontWeight.BOLD),
                    self.auto_start_checkbox,
                    self.start_minimized_checkbox,
                    self.auto_run_checkbox,
                ]
            ),
            padding=15,
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=8,
        )

        # 操作按钮
        self.start_btn = ft.ElevatedButton(
            "启动服务",
            icon=ft.Icons.PLAY_ARROW,
            on_click=self._start_server,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN, color=ft.Colors.WHITE),
        )
        self.stop_btn = ft.ElevatedButton(
            "停止服务",
            icon=ft.Icons.STOP,
            on_click=self._stop_server,
            disabled=True,
            style=ft.ButtonStyle(bgcolor=ft.Colors.RED, color=ft.Colors.WHITE),
        )
        save_btn = ft.ElevatedButton(
            "保存配置",
            icon=ft.Icons.SAVE,
            on_click=self._save_settings,
        )

        buttons_row = ft.Row(
            [self.start_btn, self.stop_btn, save_btn],
            alignment=ft.MainAxisAlignment.CENTER,
        )

        # 日志区域
        self.log_list = ft.ListView(
            expand=True,
            spacing=2,
            auto_scroll=True,
        )

        log_container = ft.Container(
            content=ft.Column(
                [
                    ft.Text("日志", weight=ft.FontWeight.BOLD),
                    ft.Container(
                        content=self.log_list,
                        height=150,
                        border=ft.border.all(1, ft.Colors.OUTLINE),
                        border_radius=8,
                        padding=10,
                    ),
                ]
            ),
        )

        # 组装页面
        self.page.add(
            ft.Column(
                [
                    status_row,
                    server_config,
                    iflow_config,
                    app_settings,
                    buttons_row,
                    log_container,
                ],
                spacing=15,
                expand=True,
            )
        )

        self._add_log("应用已启动")

    def _add_log(self, message: str):
        """添加日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_list.controls.append(
            ft.Text(f"[{timestamp}] {message}", size=12, selectable=True)
        )
        # 限制日志数量
        if len(self.log_list.controls) > 100:
            self.log_list.controls.pop(0)
        self.page.update()

    def _on_pubsub_message(self, message):
        """处理 pubsub 消息 - 在主线程中执行"""
        if isinstance(message, dict) and message.get("type") == "server_state":
            state = message["state"]
            msg = message["message"]
            self._on_server_state_change(state, msg)

    def _on_server_state_change_threadsafe(self, state: ServerState, message: str):
        """服务状态变化回调 - 线程安全版本，从后台线程调用"""
        # 通过 pubsub 发送消息到主线程
        try:
            self.page.pubsub.send_all(
                {"type": "server_state", "state": state, "message": message}
            )
        except Exception:
            pass

    def _on_server_state_change(self, state: ServerState, message: str):
        """服务状态变化回调 - 必须在主线程调用"""
        state_config = {
            ServerState.STOPPED: (ft.Colors.GREY, "服务未运行"),
            ServerState.STARTING: (ft.Colors.ORANGE, "服务启动中..."),
            ServerState.RUNNING: (
                ft.Colors.GREEN,
                f"服务运行中 (http://{self.settings.host}:{self.settings.port})",
            ),
            ServerState.STOPPING: (ft.Colors.ORANGE, "服务停止中..."),
            ServerState.ERROR: (ft.Colors.RED, f"错误: {message}"),
        }

        color, text = state_config.get(state, (ft.Colors.GREY, "未知状态"))
        self.status_icon.color = color
        self.status_text.value = text

        # 更新按钮状态
        is_running = state == ServerState.RUNNING
        is_busy = state in (ServerState.STARTING, ServerState.STOPPING)
        self.start_btn.disabled = is_running or is_busy
        self.stop_btn.disabled = not is_running or is_busy

        self._add_log(text)
        self.page.update()

    def _start_server(self, e):
        """启动服务"""
        self._update_settings_from_ui()
        if self.server.start(self.settings):
            self._add_log("正在启动服务...")

    def _stop_server(self, e):
        """停止服务"""
        if self.server.stop():
            self._add_log("正在停止服务...")

    def _save_settings(self, e):
        """保存配置"""
        self._update_settings_from_ui()
        save_settings(self.settings)
        self._add_log("配置已保存")

        # 显示提示
        self.page.open(
            ft.SnackBar(content=ft.Text("配置已保存"), bgcolor=ft.Colors.GREEN)
        )

    def _update_settings_from_ui(self):
        """从 UI 更新配置"""
        self.settings.host = self.host_field.value or "0.0.0.0"
        try:
            self.settings.port = int(self.port_field.value or "8000")
        except ValueError:
            self.settings.port = 8000
        self.settings.api_key = self.api_key_field.value or ""
        self.settings.base_url = self.base_url_field.value or "https://apis.iflow.cn/v1"
        self.settings.start_minimized = self.start_minimized_checkbox.value
        self.settings.auto_run_server = self.auto_run_checkbox.value

    def _import_from_cli(self, e):
        """从 iFlow CLI 导入配置"""
        config = import_from_iflow_cli()
        if config:
            self.api_key_field.value = config.api_key
            self.base_url_field.value = config.base_url
            self.page.update()
            self._add_log("已从 iFlow CLI 导入配置")
            self.page.open(
                ft.SnackBar(
                    content=ft.Text("已从 iFlow CLI 导入配置"), bgcolor=ft.Colors.GREEN
                )
            )
        else:
            self._add_log("无法导入 iFlow CLI 配置")
            self.page.open(
                ft.SnackBar(
                    content=ft.Text("无法导入配置，请确保已运行 iflow 并完成登录"),
                    bgcolor=ft.Colors.RED,
                )
            )

    def _on_auto_start_change(self, e):
        """开机自启动设置变化"""
        success = set_auto_start(e.control.value)
        if success:
            self._add_log(f"开机自启动已{'启用' if e.control.value else '禁用'}")
        else:
            e.control.value = not e.control.value
            self.page.update()
            self._add_log("设置开机自启动失败")

    def _login_with_iflow_oauth(self, e):
        """使用 iFlow OAuth 登录"""
        from .oauth_login import OAuthLoginHandler

        handler = OAuthLoginHandler(self._add_log)
        handler.start_login()


def main(page: ft.Page):
    """Flet 应用入口"""
    IFlow2ApiApp(page)


if __name__ == "__main__":
    ft.run(main)
