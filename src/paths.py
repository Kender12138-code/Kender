"""项目内数据文件的统一路径（唯一入口）。

为什么单独抽出来：data/ 下放的是长期记忆、提醒清单、FAISS 索引、MCP 日志这些
"跑起来才产生"的文件。以前各模块各写各的相对路径 "data/xxx"，一旦进程的工作目录
不是项目根（Docker、计划任务、从别处 import 调用），文件就会写到别的地方或读不到，
表现为"记忆时灵时不灵""提醒创建了却看不到"。

src/memory.py 在 2026-09-09 单独修过一次，这里是那次修复的推广：全项目共用同一份
根目录推算逻辑。mcp_server/reminder_server.py 是独立脚本、不能用相对导入，
它按同样规则自己算一份（见该文件注释）。
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


def data_path(name: str = "") -> str:
    """返回 data/ 下的绝对路径（字符串）。父目录是否创建由调用方决定。"""
    return str(DATA_DIR / name) if name else str(DATA_DIR)


def ensure_data_dir() -> str:
    """确保 data/ 存在，并返回它的绝对路径。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return str(DATA_DIR)
