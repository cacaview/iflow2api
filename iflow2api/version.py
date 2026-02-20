"""版本信息和系统诊断工具

支持平台：Windows, Linux, macOS (Darwin)
支持环境：Docker, Kubernetes, WSL, VSCode, PyCharm, Jupyter, SSH
"""

import os
import sys
import platform
from datetime import datetime
from typing import Optional


# 从 pyproject.toml 读取的版本号
# 注意：安装后可以通过 importlib.metadata 获取
__version__ = "1.4.7"


def get_version() -> str:
    """获取版本号"""
    # 尝试从安装的包元数据获取版本
    try:
        from importlib.metadata import version as get_pkg_version
        return get_pkg_version("iflow2api")
    except Exception:
        # 回退到硬编码版本
        return __version__


def get_platform_info() -> dict:
    """获取平台信息
    
    支持的平台：
    - Windows: platform.system() == "Windows"
    - Linux: platform.system() == "Linux"
    - macOS: platform.system() == "Darwin"
    """
    info = {
        "system": platform.system(),  # Windows, Linux, Darwin
        "system_version": platform.version(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_implementation": platform.python_implementation(),  # CPython, PyPy
        "architecture": platform.machine(),  # x86_64, AMD64, ARM64, aarch64
        "hostname": platform.node()[:20],  # 主机名（截断）
    }
    return info


def is_wsl() -> bool:
    """检测是否在 Windows Subsystem for Linux (WSL) 中运行
    
    WSL 检测方法：
    1. 检查 /proc/version 是否包含 "microsoft" 或 "WSL"
    2. 检查 WSL_DISTRO_NAME 环境变量
    """
    # 检查 WSL 特有的环境变量
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    
    # 检查 /proc/version (仅 Linux)
    if platform.system() == "Linux":
        try:
            with open("/proc/version", "r") as f:
                content = f.read().lower()
                if "microsoft" in content or "wsl" in content:
                    return True
        except Exception:
            pass
    
    return False


def is_docker() -> bool:
    """检测是否在 Docker 容器中运行
    
    Docker 检测方法：
    1. 检查 /.dockerenv 文件 (Linux 容器)
    2. 检查 /proc/1/cgroup 是否包含 docker 或 kubepods (Linux)
    3. 检查环境变量 DOCKER_CONTAINER 或 KUBERNETES_SERVICE_HOST
    """
    # 检查 Docker 特有的环境变量
    if os.environ.get("DOCKER_CONTAINER"):
        return True
    
    # 检查 /.dockerenv 文件 (Linux 容器)
    if os.path.exists("/.dockerenv"):
        return True
    
    # 检查 /proc/1/cgroup (仅 Linux)
    if platform.system() == "Linux":
        try:
            with open("/proc/1/cgroup", "r") as f:
                content = f.read()
                if "docker" in content or "kubepods" in content:
                    return True
        except Exception:
            pass
    
    return False


def is_kubernetes() -> bool:
    """检测是否在 Kubernetes 中运行"""
    return bool(os.environ.get("KUBERNETES_SERVICE_HOST"))


def get_runtime_env() -> str:
    """获取运行环境描述
    
    检测优先级：
    1. Kubernetes (在容器编排环境中)
    2. Docker (在容器中)
    3. WSL (Windows Subsystem for Linux)
    4. IDE 环境 (VSCode, PyCharm)
    5. Jupyter Notebook
    6. SSH 远程连接
    7. 本地环境
    """
    if is_kubernetes():
        return "Kubernetes"
    elif is_docker():
        return "Docker"
    elif is_wsl():
        return "WSL"
    elif os.environ.get("TERM_PROGRAM") == "vscode":
        return "VSCode"
    elif os.environ.get("PYCHARM_HOSTED"):
        return "PyCharm"
    elif os.environ.get("JUPYTER_NOTEBOOK"):
        return "Jupyter"
    elif os.environ.get("SSH_CONNECTION"):
        return "SSH"
    else:
        return "Local"


def get_os_display_name() -> str:
    """获取操作系统的显示名称
    
    返回更友好的操作系统名称：
    - Windows 10/11
    - Ubuntu 22.04 / Debian 12 / CentOS 7 等
    - macOS 14.x (Sonoma) 等
    """
    system = platform.system()
    
    if system == "Windows":
        # Windows 版本检测
        version = platform.version()
        try:
            # Windows 10 和 11 的主版本号都是 10
            # 通过构建号区分
            build = int(version.split('.')[-1]) if '.' in version else 0
            if build >= 22000:
                return "Windows 11"
            else:
                return "Windows 10"
        except Exception:
            return "Windows"
    
    elif system == "Darwin":
        # macOS 版本检测
        try:
            # macOS 版本号映射
            mac_version = platform.mac_ver()[0]
            if mac_version:
                major = int(mac_version.split('.')[0])
                version_names = {
                    14: "Sonoma",
                    13: "Ventura",
                    12: "Monterey",
                    11: "Big Sur",
                }
                name = version_names.get(major, "")
                return f"macOS {mac_version}" + (f" ({name})" if name else "")
        except Exception:
            pass
        return "macOS"
    
    elif system == "Linux":
        # Linux 发行版检测
        try:
            # 尝试读取 /etc/os-release
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r") as f:
                    lines = f.readlines()
                    info = {}
                    for line in lines:
                        if "=" in line:
                            key, value = line.strip().split("=", 1)
                            info[key] = value.strip('"')
                    
                    name = info.get("NAME", "Linux")
                    version = info.get("VERSION_ID", "")
                    if version:
                        return f"{name} {version}"
                    return name
        except Exception:
            pass
        return "Linux"
    
    else:
        return system


def get_startup_info() -> str:
    """获取启动信息字符串，用于日志输出"""
    version = get_version()
    platform_info = get_platform_info()
    runtime = get_runtime_env()
    os_name = get_os_display_name()
    
    lines = [
        "=" * 60,
        f"  iflow2api v{version}",
        "=" * 60,
        f"  系统: {os_name}",
        f"  平台: {platform_info['system']} {platform_info['architecture']}",
        f"  Python: {platform_info['python_version']} ({platform_info['python_implementation']})",
        f"  环境: {runtime}",
        f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
    ]
    return "\n".join(lines)


def get_diagnostic_info() -> dict:
    """获取诊断信息字典，用于错误报告"""
    return {
        "version": get_version(),
        "os": get_os_display_name(),
        "platform": get_platform_info(),
        "runtime": get_runtime_env(),
        "docker": is_docker(),
        "kubernetes": is_kubernetes(),
        "wsl": is_wsl(),
    }


def format_diagnostic_for_issue() -> str:
    """格式化诊断信息用于 issue 报告"""
    info = get_diagnostic_info()
    lines = [
        "## 环境信息",
        "",
        f"- **版本**: iflow2api v{info['version']}",
        f"- **系统**: {info['os']}",
        f"- **平台**: {info['platform']['system']} {info['platform']['architecture']}",
        f"- **Python**: {info['platform']['python_version']}",
        f"- **环境**: {info['runtime']}",
        f"- **Docker**: {'是' if info['docker'] else '否'}",
        f"- **Kubernetes**: {'是' if info['kubernetes'] else '否'}",
        f"- **WSL**: {'是' if info['wsl'] else '否'}",
    ]
    return "\n".join(lines)
