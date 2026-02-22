"""日志系统统一配置

解决问题：GUI 界面和 Web 界面日志区域无法显示命令行运行日志。

原因：
  1. Web  界面 /admin/logs 从 ~/.iflow2api/logs/app.log 读取，但从未配置 FileHandler 写入该文件。
  2. GUI  界面 _add_log() 只接收显式 pubsub 消息，Python logging 调用不经过 GUI 列表。

修复：
  - setup_file_logging() 为 iflow2api / uvicorn 等 logger 添加 RotatingFileHandler，
    同时保留控制台输出，确保 CLI 模式下日志既在终端可见，又落盘供 Web 界面读取。
  - GUILogHandler  将 logging 记录实时转发到 Flet GUI 的 pubsub，GUI 日志列表即可
    实时显示所有 logger.info/warning/error 产生的消息。
"""

import logging
import logging.handlers
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 写入文件的 logger 名称列表
_FILE_LOGGER_NAMES = (
    "iflow2api",
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
    "fastapi",
)

# 单例 file handler，避免重复添加
_file_handler: Optional[logging.handlers.RotatingFileHandler] = None


# ---------------------------------------------------------------------------
# 公共接口
# ---------------------------------------------------------------------------


def get_log_file_path() -> Path:
    """返回应用日志文件路径"""
    return Path.home() / ".iflow2api" / "logs" / "app.log"


def setup_file_logging(level: int = logging.INFO) -> Path:
    """配置文件日志（幂等，可重复调用）。

    - 为 iflow2api / uvicorn 等 logger 添加 RotatingFileHandler（写入 app.log）
    - 若 iflow2api logger 尚无 StreamHandler，则同时添加控制台输出

    Returns:
        日志文件路径
    """
    global _file_handler

    log_file = get_log_file_path()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # ---------- 1. 创建 / 复用文件 handler ----------
    if _file_handler is None:
        _file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5 MB per file
            backupCount=3,
            encoding="utf-8",
        )
        _file_handler.setFormatter(formatter)
        _file_handler.setLevel(level)

    # ---------- 2. 配置 iflow2api logger ----------
    iflow_logger = logging.getLogger("iflow2api")
    iflow_logger.setLevel(level)

    # 确保不重复添加同类型 handler
    existing_types = {type(h) for h in iflow_logger.handlers}

    if logging.handlers.RotatingFileHandler not in existing_types:
        iflow_logger.addHandler(_file_handler)

    # 若当前没有任何 StreamHandler，补充控制台输出
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in iflow_logger.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        iflow_logger.addHandler(console_handler)

    # 阻止向 root logger 继续传播（避免重复输出）
    iflow_logger.propagate = False

    # ---------- 3. 让 uvicorn / fastapi logger 也写入文件，同时保留控制台输出 ----------
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"):
        lg = logging.getLogger(name)
        lg.setLevel(level)
        existing = {type(h) for h in lg.handlers}

        if logging.handlers.RotatingFileHandler not in existing:
            lg.addHandler(_file_handler)

        # 若没有任何 StreamHandler，补充控制台输出
        # （当 uvicorn 以 log_config=None 启动时不会自动添加控制台 handler）
        if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
                   for h in lg.handlers):
            ch = logging.StreamHandler()
            ch.setFormatter(formatter)
            ch.setLevel(level)
            lg.addHandler(ch)

    return log_file


def add_gui_log_handler(page) -> "GUILogHandler":
    """为 iflow2api logger 添加 GUI 实时日志 handler，并返回该 handler。

    Args:
        page: Flet page 对象

    Returns:
        已添加的 GUILogHandler 实例
    """
    handler = GUILogHandler(page)
    handler.setLevel(logging.INFO)

    iflow_logger = logging.getLogger("iflow2api")
    # 避免重复添加
    if not any(isinstance(h, GUILogHandler) for h in iflow_logger.handlers):
        iflow_logger.addHandler(handler)

    return handler


def remove_gui_log_handler(page) -> None:
    """移除与指定 page 关联的 GUILogHandler（在窗口销毁时调用）。"""
    iflow_logger = logging.getLogger("iflow2api")
    to_remove = [h for h in iflow_logger.handlers
                 if isinstance(h, GUILogHandler) and h.page is page]
    for h in to_remove:
        iflow_logger.removeHandler(h)
        h.close()


# ---------------------------------------------------------------------------
# Handler 类
# ---------------------------------------------------------------------------


class GUILogHandler(logging.Handler):
    """将 logging 记录实时转发到 Flet GUI pubsub 的 Handler。

    GUI 侧通过 pubsub 收到 {"type": "add_log", "message": "..."} 消息后
    在 _on_pubsub_message 中调用 _add_log() 更新界面。
    """

    def __init__(self, page):
        super().__init__()
        self.page = page
        # 只显示消息内容，不重复时间戳（GUI 已自行添加时间戳）
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            # pubsub.send_all 线程安全，可从后台线程调用
            self.page.pubsub.send_all({"type": "add_log", "message": msg})
        except Exception:
            self.handleError(record)
