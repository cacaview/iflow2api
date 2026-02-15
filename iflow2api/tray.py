"""系统托盘模块

跨平台系统托盘支持：
- Windows: 使用 pystray
- macOS: 使用 pystray (菜单栏图标)
- Linux: 使用 pystray (需要 AppIndicator 支持)
"""

import threading
from typing import Callable, Optional
from PIL import Image, ImageDraw

try:
    import pystray
    from pystray import MenuItem, Menu
    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False


class TrayManager:
    """系统托盘管理器"""

    def __init__(
        self,
        on_show_window: Optional[Callable] = None,
        on_start_server: Optional[Callable] = None,
        on_stop_server: Optional[Callable] = None,
        on_quit: Optional[Callable] = None,
    ):
        """初始化托盘管理器

        Args:
            on_show_window: 显示主窗口的回调
            on_start_server: 启动服务的回调
            on_stop_server: 停止服务的回调
            on_quit: 退出应用的回调
        """
        self.on_show_window = on_show_window
        self.on_start_server = on_start_server
        self.on_stop_server = on_stop_server
        self.on_quit = on_quit

        self._icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None
        self._is_running = False
        self._server_running = False

    def _create_icon_image(self, color: str = "gray") -> Image.Image:
        """创建托盘图标

        Args:
            color: 图标颜色 (gray=停止, green=运行, orange=启动中)

        Returns:
            PIL Image 对象
        """
        # 创建 64x64 的图标
        width = 64
        height = 64
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        dc = ImageDraw.Draw(image)

        # 颜色映射
        color_map = {
            "gray": (128, 128, 128, 255),      # 停止
            "green": (76, 175, 80, 255),       # 运行中
            "orange": (255, 152, 0, 255),      # 启动中
            "red": (244, 67, 54, 255),         # 错误
        }
        fill_color = color_map.get(color, color_map["gray"])

        # 绘制圆形图标
        padding = 8
        dc.ellipse(
            [(padding, padding), (width - padding, height - padding)],
            fill=fill_color,
        )

        # 如果是运行状态，添加一个小的播放三角形
        if color == "green":
            triangle_points = [
                (width // 2 - 6, height // 2 - 8),
                (width // 2 - 6, height // 2 + 8),
                (width // 2 + 10, height // 2),
            ]
            dc.polygon(triangle_points, fill=(255, 255, 255, 255))

        return image

    def _get_menu(self) -> Menu:
        """获取托盘菜单"""
        return Menu(
            MenuItem(
                "打开主界面",
                self._on_show_window,
                default=True,  # 双击触发
            ),
            Menu.SEPARATOR,
            MenuItem(
                "启动服务",
                self._on_start_server,
                visible=lambda item: not self._server_running,
            ),
            MenuItem(
                "停止服务",
                self._on_stop_server,
                visible=lambda item: self._server_running,
            ),
            Menu.SEPARATOR,
            MenuItem(
                "退出",
                self._on_quit,
            ),
        )

    def _on_show_window(self, icon, item):
        """显示主窗口"""
        if self.on_show_window:
            self.on_show_window()

    def _on_start_server(self, icon, item):
        """启动服务"""
        if self.on_start_server:
            self.on_start_server()

    def _on_stop_server(self, icon, item):
        """停止服务"""
        if self.on_stop_server:
            self.on_stop_server()

    def _on_quit(self, icon, item):
        """退出应用"""
        self.stop()
        if self.on_quit:
            self.on_quit()

    def update_status(self, is_running: bool, status: str = "normal"):
        """更新托盘状态

        Args:
            is_running: 服务是否正在运行
            status: 状态类型 (normal, starting, error)
        """
        self._server_running = is_running

        if self._icon:
            if status == "starting":
                color = "orange"
            elif status == "error":
                color = "red"
            elif is_running:
                color = "green"
            else:
                color = "gray"

            try:
                self._icon.icon = self._create_icon_image(color)
                self._icon.menu = self._get_menu()
            except Exception:
                pass

    def start(self):
        """启动托盘（在后台线程中运行）"""
        if not PYSTRAY_AVAILABLE:
            return

        if self._is_running:
            return

        def run_tray():
            try:
                self._icon = pystray.Icon(
                    "iflow2api",
                    icon=self._create_icon_image("gray"),
                    title="iflow2api",
                    menu=self._get_menu(),
                )
                self._is_running = True
                self._icon.run()
            except Exception:
                self._is_running = False

        self._thread = threading.Thread(target=run_tray, daemon=True)
        self._thread.start()

    def stop(self):
        """停止托盘"""
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
        self._is_running = False

    def is_available(self) -> bool:
        """检查托盘功能是否可用"""
        return PYSTRAY_AVAILABLE


def is_tray_available() -> bool:
    """检查系统托盘功能是否可用"""
    return PYSTRAY_AVAILABLE
