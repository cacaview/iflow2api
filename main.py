"""Flet 应用入口"""
import flet as ft
from iflow2api.gui import IFlow2ApiApp
from iflow2api.logging_setup import setup_file_logging


def main(page: ft.Page):
    IFlow2ApiApp(page)


if __name__ == "__main__":
    # GUI 模式：初始化文件日志，确保日志写入文件供 Web 界面读取
    setup_file_logging()
    ft.run(main)
