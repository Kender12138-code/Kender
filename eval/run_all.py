"""一条命令跑完全部评测套件。

用法：
    python eval/run_all.py            # 跑一轮，打印汇总表
    python eval/run_all.py --repeat 2 # 连跑两轮，用来看稳定性
    python eval/run_all.py --quiet    # 只打汇总

退出码：全部通过 0，有失败 1（可以直接挂到 CI 上）。

为什么用子进程而不是 import：每个套件的 RAG 索引目录不同
（普通套件要 --no-rag-index，RAG 套件要 --rag-fixture），
用环境变量隔离最干净，也不会让上一套的 agent 状态漏到下一套。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
RUNNER = EVAL_DIR / "runner.py"

# (名字, 用例文件, 额外参数)
SUITES = [
    ("基础", EVAL_DIR / "cases.jsonl", ["--no-rag-index"]),
    ("难题", EVAL_DIR / "cases_hard.jsonl", ["--no-rag-index"]),
    ("多轮", EVAL_DIR / "cases_multiturn.jsonl", ["--no-rag-index"]),
    ("边界", EVAL_DIR / "cases_edge.jsonl", ["--no-rag-index"]),
    ("查库", EVAL_DIR / "cases_db.jsonl", ["--no-rag-index"]),
    ("技能", EVAL_DIR / "cases_skill.jsonl", ["--no-rag-index"]),
    (
        "文档",
        EVAL_DIR / "cases_rag.jsonl",
        ["--rag-fixture", str(EVAL_DIR / "fixtures" / "星链项目说明.md")],
    ),
]


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001, S110
            pass


def run_suite(name: str, cases: Path, extra: list[str], quiet: bool) -> tuple[int, int]:
    cmd = [sys.executable, str(RUNNER), "--cases", str(cases), "--llm-judge",
           "--isolate-skills", *extra]
    proc = subprocess.run(
        cmd,
        cwd=str(EVAL_DIR.parent),
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    out = proc.stdout + proc.stderr
    if not quiet:
        print(out)
    passed = total = 0
    for line in out.splitlines():
        if "有效通过" in line:
            part = line.split("有效通过")[1]
            frac = part.split("=")[0].strip()
            if "/" in frac:
                a, b = frac.split("/")
                passed, total = int(a), int(b)
    return passed, total


def main() -> int:
    _utf8()
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    grand_pass = grand_total = 0
    rows = []
    for rnd in range(args.repeat):
        for name, cases, extra in SUITES:
            passed, total = run_suite(name, cases, extra, args.quiet)
            rows.append((rnd + 1, name, passed, total))
            grand_pass += passed
            grand_total += total

    print()
    print(f"{'轮':<3}{'套件':<6}{'通过':>6}{'总数':>6}{'通过率':>8}")
    print("-" * 32)
    for rnd, name, passed, total in rows:
        rate = f"{passed / total:.0%}" if total else "—"
        print(f"{rnd:<3}{name:<6}{passed:>6}{total:>6}{rate:>8}")
    print("-" * 32)
    overall = grand_pass / grand_total if grand_total else 0
    print(f"{'合计':<9}{grand_pass:>6}{grand_total:>6}{overall:>8.0%}")

    return 0 if grand_pass == grand_total else 1


if __name__ == "__main__":
    sys.exit(main())
