"""Kender 评测跑批（eval runner）。

用途：把「我觉得它变好了」换成「30 条用例通过率从 X% 到 Y%」。

用法：
    python eval/runner.py                # 跑全部 30 条
    python eval/runner.py --limit 5      # 只跑前 5 条（调试用）
    python eval/runner.py --cat weather  # 只跑某一类
    python eval/runner.py --only W01,C01 # 指定 id
    python eval/runner.py --no-critic    # 跳过 Critic，只看生成（更快更便宜）

产物：
    eval/results/<run_id>/results.jsonl  每条用例的完整记录
    eval/results/<run_id>/report.md      人看的报告

设计要点（面试可讲）：
1. 每条用例用一个全新 agent + 空白记忆 —— 避免上一题的上下文影响下一题。
2. persist=False —— 评测绝不能污染真实的 data/kender_memory.json。
3. 判定用「规则」，不用 LLM —— 可复现、零额外 token、失败原因可解释。
4. 同时记录轨迹（trace）、工具调用、耗时 —— 后面接 trace 落库时直接复用。
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# --- 必须在 import src.* 之前设置，避免评测时拉起 MCP 子进程 ---
os.environ.setdefault("KENDER_ENABLE_MCP", "0")

# Windows 控制台默认 GBK，AgentScope 会把模型思考过程打到 stdout，
# 一旦模型输出 emoji 就会 UnicodeEncodeError，把正常回答变成"调用模型出错"。
# 这里强制 UTF-8，保证评测跑得下去（这也是 Kender 在 Windows 上的真实缺陷）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001, S110
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import trace as trace_store

from judge_llm import llm_judge

from src.agent import (
    _stringify_tool_output,
    create_agent,
    get_reply_with_review,
    get_reply_with_trace,
)
from src.tools import get_current_date

TOOL_RE = re.compile(r"调用 `([^`]+)`")


def blank_memory() -> dict:
    """空白记忆：结构必须与 src/memory.py 的持久化格式一致。"""
    return {"user_name": None, "key_facts": [], "chat_history": []}


def parse_tools(trace: str) -> list[str]:
    """从轨迹文本里抽出工具名（保持顺序、去重）。"""
    seen, out = set(), []
    for name in TOOL_RE.findall(trace or ""):
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


TOOL_ERROR_MARKERS = (
    "timed out", "Timeout", "timeout", "连接失败", "ECONN", "Connection",
    "搜索出错", "天气查询失败", "URLError", "getaddrinfo", "SSLError", "HTTP Error",
)
# 平台侧错误：DashScope 内容审核拦截、限流、网关 5xx 等
API_ERROR_MARKERS = (
    "DataInspectionFailed",
    "调用模型时出错了",
    "Failed to get response",
    "rate limit",
    "Throttling",
)


async def inspect_memory(agent) -> tuple[list[str], bool, int]:
    """直接从 agent.memory 提取本轮所有工具调用（跨重试、跨轮次累积）。

    为什么不用返回的 trace：Critic 打回重写时，第二轮往往不再调工具，
    trace 只反映最后一轮，会把"调用过工具"误判成"没调"。
    memory 是累积的，取并集才准。

    Returns:
        (工具名列表, 是否发生工具层错误, 工具调用总次数)
    """
    tools: list[str] = []
    outputs: list[str] = []
    calls = 0
    try:
        mem = await agent.memory.get_memory()
    except Exception:  # noqa: BLE001
        return [], False, 0
    for m in mem:
        content = getattr(m, "content", None)
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                calls += 1
                name = b.get("name")
                if name and name not in tools:
                    tools.append(name)
            elif b.get("type") == "tool_result":
                out = b.get("output")
                outputs.append(out if isinstance(out, str) else _stringify_tool_output(out))
    blob = "\n".join(outputs)
    tool_error = any(k in blob for k in TOOL_ERROR_MARKERS)
    evidence = "\n---\n".join(o[:600] for o in outputs[-4:])
    return tools, tool_error, calls, evidence


async def collect_steps(agent) -> list[dict]:
    """把 memory 里的 tool_use / tool_result 配对成可入库的步骤列表。"""
    try:
        mem = await agent.memory.get_memory()
    except Exception:  # noqa: BLE001
        return []
    steps: list[dict] = []
    pending: dict[str, dict] = {}
    for m in mem:
        content = getattr(m, "content", None)
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                item = {
                    "tool": b.get("name"),
                    "args": json.dumps(b.get("input") or {}, ensure_ascii=False),
                    "output": "",
                }
                pending[b.get("id")] = item
                steps.append(item)
            elif b.get("type") == "tool_result":
                item = pending.get(b.get("id"))
                if item is not None:
                    item["output"] = _stringify_tool_output(b.get("output"))[:1500]
    for i, s in enumerate(steps, 1):
        s["step"] = i
    return steps


def load_cases(path: Path) -> list[dict]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def _run_extra_checks(reply: str, specs: list[str]) -> list[str]:
    """执行用例自定义的硬性检查，返回失败描述列表。

    为什么不用 LLM 判"格式/禁令"：像"不要用感叹号""三句话以内"这类要求，
    用正则是确定性的、零成本的，比让模型当裁判更可靠。
    支持：
        no_exclamation      不得出现 ！或 !
        max_sentences:N     按 。！？!? 切句后不超过 N 句
        has_number:82       回答里要出现这个数字（用于单位换算等）
        max_chars:N         回答长度不超过 N 字
    """
    fails: list[str] = []
    for spec in specs or []:
        if spec == "no_exclamation":
            if "！" in reply or "!" in reply:
                fails.append("不该用感叹号")
        elif spec.startswith("max_sentences:"):
            n = int(spec.split(":", 1)[1])
            sents = [s for s in re.split(r"[。！？!?]", reply) if s.strip()]
            if len(sents) > n:
                fails.append(f"超过 {n} 句（实际 {len(sents)}）")
        elif spec.startswith("has_number:"):
            want = spec.split(":", 1)[1]
            if want not in reply:
                fails.append(f"缺数字 {want}")
        elif spec.startswith("max_chars:"):
            n = int(spec.split(":", 1)[1])
            if len(reply) > n:
                fails.append(f"超过 {n} 字（实际 {len(reply)}）")
        else:
            fails.append(f"未知检查项 {spec}")
    return fails


TOOL_NAMES = {
    "get_weather", "search_web", "query_database", "retrieve_document",
    "set_reminder", "list_skills", "read_skill", "save_skill",
    "delete_skill", "set_skill_enabled",
}


def judge(case: dict, reply: str, tools: list[str], tool_count: int = 0) -> dict:
    """规则判定，返回子项 + 总体是否通过。

    子项：
      tool_ok   工具调用是否符合预期（该调的都调了、不该调的没调）
      point_ok  回答是否覆盖了必须出现的要点（同组内任一命中即可）
      clean_ok  回答里是否出现了禁止内容（幻觉/越权承诺）
      extra_ok  用例自定义的格式/数量硬约束
    """
    used = set(tools)
    allow = set(case.get("allow", []))
    # 兼容两种写法：not_tools 明确禁用工具；not 里如果写的是工具名，也按"禁用工具"处理，
    # 其余才是"禁词"。不分开的话，模型在回答里**提到**某个工具名就会被判成违规
    # （Q03 拒绝删库时说了句 "query_database 只支持只读"，就被误伤）。
    forbid_tools = set(case.get("not_tools", [])) | {
        x for x in case.get("not", []) if x in TOOL_NAMES
    }
    forbid_words = [x for x in case.get("not", []) if x not in TOOL_NAMES]
    expect = set(case.get("tools", []))

    if expect:
        tool_ok = bool(used & expect) and not (used & forbid_tools)
    else:
        tool_ok = not (used - allow) and not (used & forbid_tools)

    missing = []
    for group in case.get("any", []):
        if not any(kw in reply for kw in group):
            missing.append("|".join(group))
    point_ok = not missing

    hits = [kw for kw in forbid_words if kw in reply]
    clean_ok = not hits

    extra_fails = _run_extra_checks(reply, case.get("extra", []))
    min_tools = int(case.get("min_tools", 0))
    if tool_count < min_tools:
        extra_fails.append(f"工具调用不足（应≥{min_tools}，实际 {tool_count}）")
    extra_ok = not extra_fails

    return {
        "tool_ok": tool_ok,
        "point_ok": point_ok,
        "clean_ok": clean_ok,
        "extra_ok": extra_ok,
        "passed": tool_ok and point_ok and clean_ok and extra_ok,
        "tools_used": sorted(used),
        "missing_points": missing,
        "forbidden_hits": hits,
        "extra_fails": extra_fails,
    }


async def run_case(case: dict, use_critic: bool, judge_model=None) -> dict:
    memory = blank_memory()
    buf = io.StringIO()
    t0 = time.perf_counter()
    error = None
    verdict_passed, verdict_reason, rounds = None, "", 1
    reply, trace = "", ""
    # 多轮用例：turns 是一串用户消息，跑在同一个 agent 上（上下文连续）。
    # 单轮用例退化成 turns = [q]。
    turns = case.get("turns") or [case["q"]]
    replies: list[str] = []
    question = " → ".join(turns)

    # 整段重定向 stdout：AgentScope 会把思考过程和工具调用打到控制台，
    # 30 条用例跑下来会淹没进度输出。这里收进 buffer，失败时再回看。
    with contextlib.redirect_stdout(buf):
        try:
            agent, model = create_agent(memory)
            for turn in turns:
                if use_critic:
                    reply, trace, verdict, rounds = await get_reply_with_review(
                        agent, model, turn, memory, persist=False
                    )
                    verdict_passed = bool(verdict.passed)
                    verdict_reason = verdict.reason
                else:
                    reply, trace = await get_reply_with_trace(agent, model, turn, memory)
                replies.append(reply)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"

    reply = replies[-1] if replies else reply
    latency = time.perf_counter() - t0
    if error:
        tools, tool_error, tool_count, evidence = parse_tools(trace), False, 0, ""
    else:
        tools, tool_error, tool_count, evidence = await inspect_memory(agent)
    # 平台侧拦截/限流也算环境问题，不能算模型能力
    if any(k in reply for k in API_ERROR_MARKERS):
        tool_error = True
    result = judge(case, reply, tools, tool_count)

    # 多轮用例的逐轮判定：原来只看最后一轮，中间轮答错会漏掉。
    # turn_expect 支持每轮写 any（必须命中的关键词组）和 not（禁止出现的词）。
    turn_failures: list[str] = []
    for idx, spec in enumerate(case.get("turn_expect") or [], start=1):
        if idx - 1 >= len(replies):
            break
        text = replies[idx - 1]
        for group in spec.get("any", []):
            if not any(kw in text for kw in group):
                turn_failures.append(f"第{idx}轮缺要点：{'|'.join(group)}")
        for kw in spec.get("not", []):
            if kw in text:
                turn_failures.append(f"第{idx}轮出现禁词：{kw}")
        # 需要判断"语义上有没有做到"的轮次，用 rubric 交给 LLM 判
        # （关键词判不了"推荐了不含香菜的菜"这种）
        if spec.get("rubric") and judge_model is not None:
            # 判定器必须看到前几轮的上下文：只看本轮"推荐一道菜"，
            # 会以为助手凭空编出"不吃香菜"这个前提（实测踩过）。
            context = "；".join(turns[: idx - 1])
            judge_question = (
                f"（前情）用户之前说过：{context}\n（本轮）用户说：{turns[idx - 1]}"
                if context
                else turns[idx - 1]
            )
            v = await llm_judge(
                judge_model,
                judge_question,
                text,
                spec["rubric"],
                evidence,
                today=get_current_date(),
            )
            if not v["ok"]:
                turn_failures.append(f"第{idx}轮判分 {v['score']}/2：{v['reason']}")
    result["turn_failures"] = turn_failures
    if turn_failures:
        result["passed"] = False

    # 有 rubric 的语义题交给 LLM 判定（规则判关键词会误伤）
    if judge_model is not None and case.get("rubric"):
        verdict = await llm_judge(
            judge_model,
            case.get("q") or question,
            reply,
            case["rubric"],
            evidence,
            today=get_current_date(),
        )
        result["llm_score"] = verdict["score"]
        result["llm_reason"] = verdict["reason"]
        result["point_ok"] = verdict["ok"]
        result["passed"] = (
            result["tool_ok"]
            and result["clean_ok"]
            and verdict["ok"]
            and not result.get("turn_failures")
        )
    else:
        result["llm_score"] = None
        result["llm_reason"] = ""
    return {
        "id": case["id"],
        "cat": case["cat"],
        "question": question,
        "reply": reply,
        "replies": replies,
        "trace": trace,
        "stdout_tail": buf.getvalue()[-1500:],
        "latency_s": round(latency, 2),
        "rounds": rounds,
        "tool_error": tool_error,
        "tool_call_count": tool_count,
        "steps": await collect_steps(agent) if not error else [],
        "evidence": evidence[:800],
        "critic_passed": verdict_passed,
        "critic_reason": verdict_reason,
        "error": error,
        **result,
    }


def write_report(run_dir: Path, results: list[dict], meta: dict) -> None:
    scored = [r for r in results if not r["tool_error"]]
    infra = [r for r in results if r["tool_error"]]
    passed = [r for r in scored if r["passed"]]

    lines = ["# Kender Eval 报告", ""]
    lines.append(f"- 时间：{meta['started_at']}")
    lines.append(f"- 用例数：{len(results)}（有效 {len(scored)}，环境失败 {len(infra)}）")
    lines.append(f"- Critic：{'开启' if meta['critic'] else '关闭'}")
    lines.append(f"- LLM 判定：{'开启' if meta.get('llm_judge') else '关闭（用关键词）'}")
    lines.append("")
    lines.append(f"**有效通过率：{len(passed)}/{len(scored)} = "
                 f"{len(passed) / max(len(scored), 1):.0%}**")
    if scored:
        lat = sorted(r["latency_s"] for r in scored)
        p50 = lat[min(len(lat) - 1, int(len(lat) * 0.5))]
        p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))]
        lines.append("")
        lines.append(f"- 延迟：P50 {p50:.1f}s / P95 {p95:.1f}s / "
                     f"平均 {sum(lat) / len(lat):.1f}s / 最慢 {lat[-1]:.1f}s")
    if infra:
        lines.append("")
        lines.append(f"> 另有 {len(infra)} 条因工具层错误（搜索超时等）未计入，"
                     f"明细见文末。")
    lines.append("")

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in scored:
        by_cat[r["cat"]].append(r)
    lines.append("## 分类通过率")
    lines.append("")
    lines.append("| 类别 | 通过/总数 | 通过率 |")
    lines.append("|---|---|---|")
    for cat, rows in sorted(by_cat.items()):
        ok = sum(1 for r in rows if r["passed"])
        lines.append(f"| {cat} | {ok}/{len(rows)} | {ok / len(rows):.0%} |")
    lines.append("")

    lines.append("## 逐条结果")
    lines.append("")
    lines.append("| ID | 类别 | 结果 | 工具 | 轮次 | 耗时 | 失败原因 |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in results:
        if r["tool_error"]:
            mark = "⚠️"
        else:
            mark = "✅" if r["passed"] else "❌"
        reasons = []
        if not r["tool_ok"]:
            reasons.append(f"工具不符（实际 {','.join(r['tools_used']) or '无'}）")
        if not r["point_ok"]:
            if r.get("llm_score") is not None:
                reasons.append(f"LLM 判分 {r['llm_score']}/2：{r['llm_reason']}")
            else:
                reasons.append("缺要点：" + "；".join(r["missing_points"]))
        if not r["clean_ok"]:
            reasons.append("出现禁词：" + "、".join(r["forbidden_hits"]))
        if not r.get("extra_ok", True):
            reasons.append("约束未满足：" + "；".join(r.get("extra_fails", [])))
        if r["error"]:
            reasons.append("异常：" + r["error"])
        if r["tool_error"]:
            reasons.append("环境/接口失败（不计分）")
        lines.append(
            f"| {r['id']} | {r['cat']} | {mark} | "
            f"{','.join(r['tools_used']) or '—'} | {r['rounds']} | {r['latency_s']}s | "
            f"{'；'.join(reasons) or '—'} |"
        )
    lines.append("")

    failed = [r for r in scored if not r["passed"]]
    if failed:
        lines.append("## 失败详情")
        lines.append("")
        for r in failed:
            lines.append(f"### {r['id']}　{r['question']}")
            lines.append("")
            lines.append(f"- 工具：{','.join(r['tools_used']) or '无'}")
            lines.append(f"- Critic：{r['critic_passed']} {r['critic_reason']}")
            lines.append(f"- 回答：{r['reply'][:300]}")
            lines.append("")

    if infra:
        lines.append("## 环境失败（不计入通过率）")
        lines.append("")
        for r in infra:
            lines.append(f"- **{r['id']}**　{r['question']}　回答：{r['reply'][:120]}")
        lines.append("")

    (run_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(Path(__file__).parent / "cases.jsonl"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--cat", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--no-critic", action="store_true")
    ap.add_argument("--llm-judge", action="store_true",
                    help="对带 rubric 的用例启用 LLM 判定（更准，每题多一次模型调用）")
    ap.add_argument("--rag-fixture", default="",
                    help="先用这个文件建一个临时 RAG 索引，供 RAG 评测使用（不碰 data/faiss_index）")
    ap.add_argument("--no-rag-index", action="store_true",
                    help="把 RAG 索引指到空目录，模拟'用户没上传文档'（评测与真实数据隔离）")
    ap.add_argument("--isolate-skills", action="store_true",
                    help="把用户技能目录指到临时目录，避免评测读写真实 data/skills")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    cases = load_cases(Path(args.cases))
    if args.cat:
        cases = [c for c in cases if c["cat"] == args.cat]
    if args.only:
        ids = {x.strip() for x in args.only.split(",") if x.strip()}
        cases = [c for c in cases if c["id"] in ids]
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print("没有匹配的用例")
        return 1

    run_id = args.out or datetime.now().strftime("run_%Y%m%d_%H%M%S")
    run_dir = Path(__file__).parent / "results" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # 技能评测会写文件，必须隔离到临时目录，别污染真实的 data/skills。
    if args.isolate_skills:
        import tempfile

        import src.skills as skills_mod

        # 直接改模块级常量：skills 里的函数都在调用时读这个全局，
        # 运行期替换就能生效（此刻再改环境变量已经晚了，模块早就导入了）。
        skills_mod.CUSTOM_SKILLS_DIR = tempfile.mkdtemp(prefix="kender_skills_eval_")
        print(f"[eval] 技能目录已隔离：{skills_mod.CUSTOM_SKILLS_DIR}")

    # 评测默认应与用户真实数据隔离：否则 data/faiss_index 里的简历会被检索到，
    # 让"这个项目/这个团队"类问题得到与用例无关的答案。
    if args.no_rag_index:
        import tempfile

        os.environ["KENDER_RAG_INDEX_DIR"] = tempfile.mkdtemp(prefix="kender_rag_none_")
        print("[eval] RAG 索引已禁用（指向空目录）")

    # RAG 评测：用指定文档建一个临时索引，通过环境变量指过去。
    # 这样不会覆盖用户真实上传的 data/faiss_index。
    if args.rag_fixture:
        import tempfile

        import src.rag as rag_mod

        text = Path(args.rag_fixture).read_text(encoding="utf-8")
        idx_dir = tempfile.mkdtemp(prefix="kender_rag_eval_")
        n_chunks = rag_mod.build_index(text, index_dir=idx_dir)
        os.environ["KENDER_RAG_INDEX_DIR"] = idx_dir
        print(f"[eval] 临时 RAG 索引：{n_chunks} 个片段 → {idx_dir}")

    meta = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "critic": not args.no_critic,
        "llm_judge": args.llm_judge,
    }

    judge_model = None
    if args.llm_judge:
        from agentscope.model import DashScopeChatModel

        judge_model = DashScopeChatModel(
            model_name=os.getenv("KENDER_JUDGE_MODEL", "qwen-plus"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            # 判定必须可复现：同一份回答两次打分不一致，评测就没有意义了
            generate_kwargs={"temperature": 0.0},
        )
        print(f"[eval] LLM 判定已启用（{os.getenv('KENDER_JUDGE_MODEL', 'qwen-plus')}）")
    print(f"[eval] {len(cases)} 条用例，critic={'on' if meta['critic'] else 'off'}")

    results = []
    for i, case in enumerate(cases, 1):
        r = await run_case(case, use_critic=not args.no_critic, judge_model=judge_model)
        trace_store.save_run(r, run_id)
        results.append(r)
        flag = "PASS" if r["passed"] else "FAIL"
        print(f"  [{i}/{len(cases)}] {r['id']:<4} {flag}  "
              f"{r['latency_s']:>5.1f}s  tools={r['tools_used'] or '-'}")

    with (run_dir / "results.jsonl").open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    write_report(run_dir, results, meta)

    scored = [r for r in results if not r["tool_error"]]
    ok = sum(1 for r in scored if r["passed"])
    print(f"\n[eval] 有效通过 {ok}/{len(scored)} = {ok / max(len(scored), 1):.0%}")
    if len(scored) < len(results):
        print(f"[eval] 环境失败 {len(results) - len(scored)} 条（不计入通过率）")
    print(f"[eval] 报告：{run_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n已中断")
        sys.exit(130)
