import os
import shutil
import subprocess
import sys
from pathlib import Path


def build():
    print("=" * 50)
    print("  iflow2api 打包脚本")
    print("=" * 50)
    print()

    try:
        import importlib.metadata

        flet_version = importlib.metadata.version("flet")
        print(f"[OK] Flet 版本: {flet_version}")
    except ImportError:
        print("[错误] Flet 未安装")
        print("请运行: pip install flet")
        sys.exit(1)

    project_dir = Path(__file__).parent
    src_dir = project_dir / "iflow2api"
    gui_script = src_dir / "gui.py"
    build_dir = project_dir / "build"

    if not gui_script.exists():
        print(f"[错误] GUI 脚本不存在: {gui_script}")
        sys.exit(1)

    if build_dir.exists():
        print("[清理] 删除旧的 build 目录...")
        shutil.rmtree(build_dir)

    try:
        print()
        print("[打包] 使用 flet pack 打包...")
        print()

        cmd = [
            "flet",
            "pack",
            str(gui_script),
            "--product-name",
            "iflow2api",
        ]

        print(f"[命令] {' '.join(cmd)}")
        print()

        result = subprocess.run(cmd, cwd=project_dir)

        if result.returncode == 0:
            print()
            print("=" * 50)
            print("  打包完成!")
            print("=" * 50)
            print()
            print(f"输出目录: {build_dir}")

            if build_dir.exists():
                for f in build_dir.rglob("*"):
                    if f.is_file():
                        size = f.stat().st_size / (1024 * 1024)
                        print(f"  - {f.relative_to(project_dir)} ({size:.1f} MB)")
        else:
            print()
            print("[错误] 打包失败")
            sys.exit(1)

    except Exception as e:
        print(f"[错误] 打包过程出现异常: {e}")
        sys.exit(1)


if __name__ == "__main__":
    build()
