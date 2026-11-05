"""查看评测轨迹（命令行）。

用法：
    python eval/show_trace.py E09              # 看某条用例最近几次的工具轨迹
    python eval/show_trace.py --stats          # 总体统计：通过率、最慢、工具使用
    python eval/show_trace.py --recent 10      # 最近 10 次运行

数据来自 eval/results/kender_trace.db（由 runner 自动写入）。
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import trace as trace_store  # noqa: E402


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def show_case(case_id: str, limit: int):
    traces = trace_store.trace_of(case_id, limit=limit)
    if not traces:
        print(f"没有找到 {case_id} 的轨迹")
        return
    for t in traces:
        print("=" * 60)
        print(f"run_id: {t['run_id']}")
        if not t["steps"]:
            print("  （没有调用工具）")
        for s in t["steps"]:
            print(f"  [{s['step']}] {s['tool']}")
            print(f"      入参: {s['args'][:120]}")
            out = (s["output"] or "").replace("\n", " ")
            print(f"      返回: {out[:160]}")


def show_recent(n: int):
    rows = trace_store.recent_runs(limit=n)
    if not rows:
        print("数据库还是空的，先跑一次 eval/runner.py")
        return
    print(f"{'时间':<20} {'用例':<6} {'结果':<5} {'工具':<22} {'耗时':>6} {'轮次':>4}")
    for r in rows:
        flag = "PASS" if r["passed"] else "FAIL"
        print(f"{r['created_at']:<20} {r['case_id']:<6} {flag:<5} "
              f"{(r['tools'] or '-')[:22]:<22} {r['latency_s']:>6.1f} {r['rounds']:>4}")


def show_stats():
    rows = trace_store.recent_runs(limit=10000)
    if not rows:
        print("数据库还是空的，先跑一次 eval/runner.py")
        return
    total = len(rows)
    passed = sum(r["passed"] for r in rows)
    print(f"总运行 {total} 次，通过 {passed} 次（{passed / total:.0%}）")

    by_case: dict[str, list[dict]] = {}
    for r in rows:
        by_case.setdefault(r["case_id"], []).append(r)

    print("\n最慢的用例（平均耗时）:")
    slow = sorted(by_case.items(), key=lambda kv: -sum(r["latency_s"] for r in kv[1]) / len(kv[1]))
    for cid, rs in slow[:5]:
        avg = sum(r["latency_s"] for r in rs) / len(rs)
        ok = sum(r["passed"] for r in rs)
        print(f"  {cid:<6} {avg:6.1f}s  {ok}/{len(rs)}")

    print("\n不稳定的用例（多次运行结果不一致）:")
    flaky = []
    for cid, rs in by_case.items():
        if len(rs) >= 2:
            ok = sum(r["passed"] for r in rs)
            if 0 < ok < len(rs):
                flaky.append((cid, ok, len(rs)))
    if not flaky:
        print("  （没有）")
    for cid, ok, n in flaky:
        print(f"  {cid:<6} {ok}/{n}")

    tools: dict[str, int] = {}
    for r in rows:
        for t in (r["tools"] or "").strip("[]").replace('"', "").split(","):
            t = t.strip()
            if t:
                tools[t] = tools.get(t, 0) + 1
    print("\n工具调用次数:")
    for t, n in sorted(tools.items(), key=lambda kv: -kv[1]):
        print(f"  {t:<20} {n}")


def main():
    _utf8()
    ap = argparse.ArgumentParser()
    ap.add_argument("case_id", nargs="?", help="要查看的用例 ID，如 E09")
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--recent", type=int, default=0)
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    if args.stats:
        show_stats()
    elif args.recent:
        show_recent(args.recent)
    elif args.case_id:
        show_case(args.case_id, args.limit)
    else:
        show_recent(10)


if __name__ == "__main__":
    main()
