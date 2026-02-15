"""跨平台开机自启动模块

支持平台:
- Windows: 注册表 HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
- macOS: LaunchAgent plist 文件
- Linux: XDG autostart desktop 文件
"""

import sys
from pathlib import Path
from typing import Optional


def get_exe_path() -> str:
    """获取当前可执行文件路径"""
    if getattr(sys, "frozen", False):
        # PyInstaller/Flet 打包后
        return sys.executable
    else:
        # 开发模式
        return f'"{sys.executable}" -m iflow2api.gui'


def set_auto_start(enabled: bool) -> bool:
    """设置开机自启动（跨平台）

    Args:
        enabled: True 启用自启动，False 禁用自启动

    Returns:
        bool: 操作是否成功
    """
    if sys.platform == "win32":
        return _set_auto_start_windows(enabled)
    elif sys.platform == "darwin":
        return _set_auto_start_macos(enabled)
    elif sys.platform.startswith("linux"):
        return _set_auto_start_linux(enabled)
    else:
        return False


def get_auto_start() -> bool:
    """检查是否已设置开机自启动（跨平台）

    Returns:
        bool: 是否已启用自启动
    """
    if sys.platform == "win32":
        return _get_auto_start_windows()
    elif sys.platform == "darwin":
        return _get_auto_start_macos()
    elif sys.platform.startswith("linux"):
        return _get_auto_start_linux()
    else:
        return False


# ==================== Windows 实现 ====================


def _set_auto_start_windows(enabled: bool) -> bool:
    """Windows: 使用注册表设置开机自启动"""
    import winreg

    app_name = "iflow2api"
    exe_path = get_exe_path()

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
        )

        if enabled:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
        else:
            try:
                winreg.DeleteValue(key, app_name)
            except FileNotFoundError:
                pass

        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _get_auto_start_windows() -> bool:
    """Windows: 检查是否已设置开机自启动"""
    import winreg

    app_name = "iflow2api"

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_QUERY_VALUE,
        )

        try:
            winreg.QueryValueEx(key, app_name)
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            winreg.CloseKey(key)
            return False
    except Exception:
        return False


# ==================== macOS 实现 ====================


def _get_launchagent_path() -> Path:
    """获取 macOS LaunchAgent plist 文件路径"""
    return Path.home() / "Library" / "LaunchAgents" / "com.iflow2api.plist"


def _generate_launchagent_plist() -> str:
    """生成 macOS LaunchAgent plist 内容"""
    exe_path = get_exe_path()
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.iflow2api</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/tmp/iflow2api.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/iflow2api.err</string>
</dict>
</plist>
'''


def _set_auto_start_macos(enabled: bool) -> bool:
    """macOS: 使用 LaunchAgent 设置开机自启动"""
    try:
        plist_path = _get_launchagent_path()

        if enabled:
            # 确保 LaunchAgents 目录存在
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            # 写入 plist 文件
            plist_content = _generate_launchagent_plist()
            plist_path.write_text(plist_content, encoding="utf-8")
        else:
            # 删除 plist 文件
            if plist_path.exists():
                plist_path.unlink()
        return True
    except Exception:
        return False


def _get_auto_start_macos() -> bool:
    """macOS: 检查是否已设置开机自启动"""
    return _get_launchagent_path().exists()


# ==================== Linux 实现 ====================


def _get_autostart_path() -> Path:
    """获取 Linux XDG autostart desktop 文件路径"""
    return Path.home() / ".config" / "autostart" / "iflow2api.desktop"


def _generate_desktop_entry() -> str:
    """生成 Linux XDG desktop entry 内容"""
    exe_path = get_exe_path()
    return f'''[Desktop Entry]
Type=Application
Name=iflow2api
Comment=iFlow API Proxy Service
Exec={exe_path}
Icon=iflow2api
Terminal=false
Categories=Network;Utility;
X-GNOME-Autostart-enabled=true
'''


def _set_auto_start_linux(enabled: bool) -> bool:
    """Linux: 使用 XDG autostart 设置开机自启动"""
    try:
        autostart_path = _get_autostart_path()

        if enabled:
            # 确保 autostart 目录存在
            autostart_path.parent.mkdir(parents=True, exist_ok=True)
            # 写入 desktop 文件
            desktop_content = _generate_desktop_entry()
            autostart_path.write_text(desktop_content, encoding="utf-8")
            # 设置可执行权限
            autostart_path.chmod(0o755)
        else:
            # 删除 desktop 文件
            if autostart_path.exists():
                autostart_path.unlink()
        return True
    except Exception:
        return False


def _get_auto_start_linux() -> bool:
    """Linux: 检查是否已设置开机自启动"""
    return _get_autostart_path().exists()


# ==================== 平台信息 ====================


def get_platform_name() -> str:
    """获取当前平台名称"""
    if sys.platform == "win32":
        return "Windows"
    elif sys.platform == "darwin":
        return "macOS"
    elif sys.platform.startswith("linux"):
        return "Linux"
    else:
        return "Unknown"


def is_auto_start_supported() -> bool:
    """检查当前平台是否支持开机自启动"""
    return sys.platform in ("win32", "darwin") or sys.platform.startswith("linux")
