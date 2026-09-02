# -*- coding: utf-8 -*-
"""环境诊断脚本：双击或在 VS Code 终端运行 `python diagnose.py` 即可。"""
import importlib.util
import os
import socket
import sys


def check_python():
    print(f"【Python 解释器】{sys.executable}")
    print(f"【Python 版本】{sys.version}")
    print()


def check_package(name, import_name=None):
    import_name = import_name or name
    try:
        spec = importlib.util.find_spec(import_name)
        if spec is None:
            return False, None
        mod = importlib.import_module(import_name)
        version = getattr(mod, "__version__", "unknown")
        return True, version
    except Exception as e:
        return False, str(e)


def check_dependencies():
    print("【依赖检查】")
    required = [
        ("agentscope", "agentscope"),
        ("gradio", "gradio"),
        ("dashscope", "dashscope"),
        ("openai", "openai"),
        ("python-dotenv", "dotenv"),
    ]
    all_ok = True
    for pkg, imp in required:
        ok, info = check_package(pkg, imp)
        if ok:
            print(f"  ✓ {pkg} == {info}")
        else:
            all_ok = False
            print(f"  ✗ {pkg} 缺失或导入失败 ({info})")
    print()
    return all_ok


def check_env():
    print("【环境变量 / .env】")
    from dotenv import load_dotenv

    load_dotenv()
    key = os.getenv("DASHSCOPE_API_KEY")
    if key and key.strip() and not key.startswith("sk-请输入"):
        print("  ✓ DASHSCOPE_API_KEY 已设置")
        return True
    elif key and key.startswith("sk-请输入"):
        print("  ✗ DASHSCOPE_API_KEY 还是占位符（sk-请输入...），请在 .env 里换成真实 key")
        return False
    else:
        print("  ✗ DASHSCOPE_API_KEY 未设置，请检查 .env 文件是否存在且包含有效 key")
        return False


def check_ports(ports=(7861, 7862)):
    print("【端口占用检查】")
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            result = s.connect_ex(("127.0.0.1", port))
            if result == 0:
                print(f"  ✗ 127.0.0.1:{port} 已被占用")
            else:
                print(f"  ✓ 127.0.0.1:{port} 空闲")
    print()


def check_imports():
    print("【项目模块导入检查】")
    try:
        import src.farm_shop
        print("  ✓ src.farm_shop 导入成功")
    except Exception as e:
        print(f"  ✗ src.farm_shop 导入失败：{e}")
    try:
        import farm_react_app
        print("  ✓ farm_react_app 导入成功")
    except Exception as e:
        print(f"  ✗ farm_react_app 导入失败：{e}")
    try:
        import farm_shop_app
        print("  ✓ farm_shop_app 导入成功")
    except Exception as e:
        print(f"  ✗ farm_shop_app 导入失败：{e}")
    print()


def main():
    print("=" * 60)
    print("  农产品电商 Agent 环境诊断")
    print("=" * 60)
    print()

    # 检查工作目录
    cwd = os.getcwd()
    expected = os.path.abspath(os.path.dirname(__file__))
    if os.path.normcase(cwd) != os.path.normcase(expected):
        print(f"⚠️  当前目录不对：{cwd}")
        print(f"   请切换到：{expected}")
        print(f"   命令：cd {expected}")
        print()
    else:
        print(f"【工作目录】{cwd} ✓")
        print()

    check_python()
    check_dependencies()
    check_env()
    check_ports()
    check_imports()

    print("=" * 60)
    print("诊断完成。如有 ✗，请按提示修复后再运行 `python farm_react_app.py`")
    print("=" * 60)


if __name__ == "__main__":
    main()
