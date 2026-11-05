# src package
#
# 导入即把控制台编码切成 UTF-8：Windows 下 GBK 编不出 emoji，
# 而 AgentScope 会把模型输出 print 到 stdout，不修就会在 .reply() 里抛异常
# （详见 src/console.py 的模块注释）。
from .console import force_utf8

force_utf8()
