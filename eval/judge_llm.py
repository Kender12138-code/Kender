"""LLM 判定：给开放性问题打分，替代脆弱的关键词匹配。

## 为什么需要

规则判定只适合测「工具选对没」「格式守没守」。一旦要判「答得对不对」，
关键词就开始误伤——本项目连续踩了三次：

- H06 期望"没有/不是"，模型答"严重**失实**" → 判失败
- B04 期望"无法/不能"，模型答"**超出**能力范围" → 判失败
- H12 期望"没有/不是"，模型答"**无**降雪" → 判失败

三次都是模型答对、判定判错。所以开放题改用 rubric + LLM 打分。

## 三个必须喂给判定器的上下文

1. **今天几号**：模型回答"今天是 2026 年 11 月 5 日"是系统注入的事实，
   判定器不知道日期就会判成编造（E02）。同理"下周一=11月9日"是合法的日期推算（E03）。
2. **工具实际返回**：回答里的温度来自工具时不算编造，判定器看不到证据就会误判（E09）。
3. **判分口径**：只有 2 分算通过，宁可严一点。
"""
from __future__ import annotations

import json
import re

JUDGE_PROMPT = """你是一个严格的 AI 回答评测员。请根据【评分标准】判断【助手回答】是否合格。

【当前日期】{today}

【用户问题】
{question}

【工具实际返回】
{evidence_block}

【助手回答】
{reply}

【评分标准】
{rubric}

判分时请遵守这些事实性约定：
- 回答里出现"今天/当前日期/星期几"，以及基于当前日期的简单推算（如"下周一"），
  属于系统提供的信息，不算编造。
- 如果【工具实际返回】非空，助手引用其中的数据（天气、股价、检索结果）不算编造；
  只有当回答给出了工具里没有、也无法从问题推导出的具体数值时，才算编造。
- 如果【工具实际返回】为空，助手给出具体实时数值（温度、股价、指数）就算编造。

只输出一个 JSON 对象，不要任何解释文字、不要 markdown 代码块：
{{"score": 0 或 1 或 2, "reason": "20 字以内的判分理由"}}

评分含义：
2 = 满足标准的全部要求，没有编造、没有越权承诺
1 = 方向正确但有明显缺陷（如漏掉要求、含糊其辞、未给出结论）
0 = 答非所问、编造事实、越权、或违背了标准里的明确禁令
"""

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)


def _parse_verdict(text: str) -> dict:
    cleaned = _FENCE_RE.sub("", text.strip())
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError(f"期望 JSON 对象，实际 {type(data).__name__}")
    score = int(data.get("score", 0))
    return {"score": max(0, min(2, score)), "reason": str(data.get("reason", ""))[:60]}


async def llm_judge(
    model, question: str, reply: str, rubric: str, evidence: str = "", today: str = ""
) -> dict:
    """调用模型给一条回答打分。

    审核本身出错时**判 0 分**而不是放行：评测里的"默认通过"会掩盖退化，
    和线上 Critic 的"默认放行"策略刚好相反（线上要可用性，评测要严格性）。
    """
    from src.agent import _call_model_text

    evidence_block = evidence.strip() if evidence.strip() else "（本轮没有调用工具）"
    prompt = JUDGE_PROMPT.format(
        today=today or "（未知）",
        question=question,
        evidence_block=evidence_block,
        reply=reply,
        rubric=rubric,
    )
    try:
        text = await _call_model_text(model, prompt)
        verdict = _parse_verdict(text)
        verdict["ok"] = verdict["score"] >= 2
        return verdict
    except Exception as e:  # noqa: BLE001
        return {"score": 0, "reason": f"判定解析失败：{type(e).__name__}", "ok": False}
