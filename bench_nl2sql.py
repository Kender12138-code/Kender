# -*- coding: utf-8 -*-
"""NL2SQL 效果评测脚本（把 8 道题固化成可重复运行的回归基准）。

用法：
    python bench_nl2sql.py                # 跑默认 8 题
    python bench_nl2sql.py --rebuild      # 重建演示库再跑

判分口径（重点）：
- 不是看 SQL "能不能跑通"，而是看**有没有答对/答错该答的题**：
    expect=run      -> 应该真的查得出结果
    expect=reject   -> 应该被引擎识别为不可查（SELECT 'NO_TABLE'）或明确报错，
                       而不是拿别的表拼一个"看起来像"的结果回来
- 最危险的失败模式是 expect=reject 却返回了别的结果（静默答错），计为 FAIL
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time

os.environ.setdefault("DB_PATH", "data/bench.db")

from src.db_tool import nl2sql  # noqa: E402  (必须在设置 DB_PATH 之后导入)

CASES = [
    ("宠物类商品一共有几个？", "run"),
    ("最近 7 天哪个商品卖得最好？", "run"),
    ("按销售额算哪个品类最好卖？", "run"),
    ("每个商品卖了多少钱，从高到低排", "run"),
    ("上个月和这个月的销售额分别是多少", "run"),
    ("所有商品的平均价格是多少", "run"),
    ("查一下库存表里库存不足的商品", "reject"),
    ("把所有订单都删掉", "reject"),
]


def build_db(path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, category TEXT, price REAL);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, product_id INTEGER, qty INTEGER,
                             amount REAL, created_at TEXT);
        INSERT INTO products VALUES
            (1,'猫粮','宠物',89.0),(2,'狗粮','宠物',129.0),(3,'猫砂','宠物',45.0),
            (4,'喂食器','硬件',399.0);
        INSERT INTO orders VALUES
            (1,1,3,267.0,date('now','-2 days')),(2,1,1,89.0,date('now','-10 days')),
            (3,2,2,258.0,date('now','-3 days')),(4,4,1,399.0,date('now','-40 days')),
            (5,3,5,225.0,date('now','-1 days'));
        """
    )
    con.commit()
    con.close()


def run_sql(sql: str, db: str):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cur = con.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    finally:
        con.close()
    return cols, rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="先重建演示数据库")
    args = ap.parse_args()

    db = os.environ["DB_PATH"]
    if args.rebuild or not os.path.exists(db):
        build_db(db)

    n_pass = n_fail = 0
    times = []
    print(f"数据库: {db}\n" + "=" * 68)
    for q, expect in CASES:
        t0 = time.time()
        try:
            sql = nl2sql(q)
            el = time.time() - t0
            times.append(el)
            if "NO_TABLE" in sql.upper():
                got = "reject"
                detail = "已拒绝（NO_TABLE）"
            else:
                cols, rows = run_sql(sql, db)
                got = "run" if rows else "empty"
                detail = f"{len(rows)} 行 -> {rows[:2]}"
            ok = got == expect
        except Exception as exc:  # noqa: BLE001
            el = time.time() - t0
            got = "reject"
            detail = f"报错拦截：{str(exc).splitlines()[0][:60]}"
            ok = expect == "reject"

        n_pass += ok
        n_fail += (not ok)
        flag = "PASS" if ok else "FAIL"
        print(f"[{flag}] {q}")
        print(f"       期望={expect} 实际={got} ({el:.2f}s) {detail}")
    print("=" * 68)
    if times:
        print(f"平均耗时 {sum(times)/len(times):.2f}s  最快 {min(times):.2f}s  最慢 {max(times):.2f}s")
    print(f"结果：{n_pass} 通过 / {n_fail} 失败（共 {len(CASES)} 题）")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
