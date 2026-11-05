# Kender Eval

把「我觉得它变好了」换成「通过率从 X% 到 Y%」。

## 怎么跑

```bash
# 四套件
python eval/runner.py                                      # 基础集 30 条
python eval/runner.py --cases eval/cases_hard.jsonl        # 难题集 12 条
python eval/runner.py --cases eval/cases_multiturn.jsonl   # 多轮 5 条
python eval/runner.py --cases eval/cases_edge.jsonl --llm-judge   # 边界 10 条

# 常用开关
python eval/runner.py --limit 5
python eval/runner.py --cat weather
python eval/runner.py --only W01,C01
python eval/runner.py --no-critic         # 跳过 Critic，更快更便宜
python eval/runner.py --llm-judge         # 对带 rubric 的题目用 LLM 判定
```

产物：`eval/results/<run_id>/` 下有 `results.jsonl`（逐条原始记录，含轨迹）和
`report.md`（人看的报告）；同时写入 `eval/results/kender_trace.db`（可 SQL 查询）。

## 数据集

| 文件 | 条数 | 覆盖 |
|---|---|---|
| `cases.jsonl` | 30 | weather / search / slot / multi / chat / boundary / doc |
| `cases_hard.jsonl` | 12 | 格式约束、抗幻觉、抗诱导、越权、单位换算、指令注入 |
| `cases_multiturn.jsonl` | 5 | 跨轮记忆、指代消解、槽位补全、偏好延续 |
| `cases_edge.jsonl` | 10 | 不存在的地点、空输入、冲突约束、三城并发、中英混排 |
| `cases_db.jsonl` | 3 | 自然语言查库（NL2SQL）：查订单数、查品类、拒绝删库 |

用例字段：

```json
{"id":"E06","cat":"edge",
 "turns":["上海天气怎么样？","那它明天呢？"],   // 多轮；单轮用 "q"
 "tools":["get_weather"],                    // 期望调用（空数组=不该调）
 "allow":["search_web"],                     // 可以调但不强求
 "not":["get_weather"],                      // 禁止调用
 "not_tools":["query_database"],             // 显式禁用工具（推荐写法）
 "min_tools":2,                              // 至少调几次
 "any":[["上海"],["度","℃","气温"]],          // 关键词要点（组内任一）
 "extra":["no_exclamation","max_sentences:1"],// 确定性格式约束
 "rubric":"第二问里的'它'必须理解为上海…"}    // 有 rubric 时走 LLM 判定
```

## 判定

### 规则判定（默认，零成本）

| 子项 | 判什么 |
|---|---|
| `tool_ok` | 该调的调了、不该调的没调（从 `agent.memory` 取并集，跨重试跨轮次） |
| `point_ok` | 关键词要点覆盖 |
| `clean_ok` | 没出现禁词 |
| `extra_ok` | 感叹号 / 句数 / 字数 / 指定数字 / 最小工具调用次数 |

### LLM 判定（`--llm-judge`）

有 `rubric` 的题目交给模型打分（0/1/2，只有 2 分算通过）。
判定器会拿到三样上下文，缺一不可：

1. **当前日期** —— 否则"今天是 2026-11-05""下周一=11-09"会被判成编造（E02/E03 踩过）
2. **工具实际返回** —— 否则基于工具数据的回答会被判成编造（E09 踩过）
3. **rubric 原文**

判定模型用 `temperature=0`，保证同一份回答两次打分一致。

**为什么必须上 LLM 判定**：关键词判定连续误伤三次——模型答"严重**失实**"、
"**超出**能力范围"、"**无**降雪"，全被判失败。规则适合测工具和格式，不适合测语义。

## 轨迹库

`eval/results/kender_trace.db` 两张表：`runs`（一次用例一行）、`steps`（一次工具调用一行）。

```bash
python eval/show_trace.py E10        # 看某条用例的工具轨迹
python eval/show_trace.py --recent 10
python eval/show_trace.py --stats    # 通过率 / 最慢用例 / 不稳定用例 / 工具使用
```

直接写 SQL 也行：

```sql
-- 每天通过率
SELECT date(created_at), AVG(passed) FROM runs GROUP BY 1;
-- 最慢用例
SELECT case_id, AVG(latency_s) FROM runs GROUP BY 1 ORDER BY 2 DESC;
```

## 环境失败的判定

搜索超时、天气接口失败、平台内容审核拦截（`DataInspectionFailed`）都算**环境问题**，
不计入通过率，单独列在报告末尾。否则基础设施抖动会被误读成模型退化。

## 已知局限

1. **规则判定仍有假阴性**：没有 rubric 的题目靠关键词，换个措辞就漏判。开放题请配 rubric。
2. **LLM 判定有成本**：每题多一次模型调用（约 1–2 秒）。日常回归可以只跑规则。
3. **多轮用例只判最后一轮**：中间轮的回答不单独判定，工具调用按累计计。
4. **不测并发/长会话**：目前都是单进程串行，没有压测。
