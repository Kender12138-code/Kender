# Kender Eval

把「我觉得它变好了」换成「通过率从 X% 到 Y%」。

## 怎么跑

```bash
# 基础集（30 条，覆盖 7 类能力）
python eval/runner.py

# 难题集（12 条，专打薄弱点）
python eval/runner.py --cases eval/cases_hard.jsonl

# 调试常用
python eval/runner.py --limit 5
python eval/runner.py --cat weather
python eval/runner.py --only W01,C01
python eval/runner.py --no-critic        # 跳过 Critic，更快更省钱
```

产物在 `eval/results/<run_id>/`：`results.jsonl`（逐条原始记录，含完整轨迹）和
`report.md`（人看的报告）。

## 两个数据集

| 文件 | 内容 | 用途 |
|---|---|---|
| `cases.jsonl` | 30 条，7 类：weather / search / slot / multi / chat / boundary / doc | 回归防线，改完别退化 |
| `cases_hard.jsonl` | 12 条：格式约束、抗幻觉、抗诱导、越权、单位换算、指令注入 | 找问题，专挑模型容易翻车的地方 |

用例字段：

```json
{"id":"W01","cat":"weather","q":"上海今天天气怎么样？",
 "tools":["get_weather"],        // 期望调用的工具（空数组=不该调）
 "allow":["retrieve_document"],  // 可以调但不强求
 "not":["get_weather"],          // 禁止调用
 "any":[["上海"],["度","℃","气温"]], // 回答必须覆盖的要点，组内任一命中即可
 "extra":["no_exclamation","max_sentences:1"]}  // 确定性硬约束
```

## 判定逻辑

四个子项全过才算 pass：

| 子项 | 判什么 | 怎么判 |
|---|---|---|
| `tool_ok` | 该调的调了、不该调的没调 | 从 `agent.memory` 里提取全部 `tool_use`（跨重试累积） |
| `point_ok` | 回答覆盖了要点 | 关键词组匹配 |
| `clean_ok` | 没出现禁词（幻觉/越权承诺） | 子串匹配 |
| `extra_ok` | 格式/数量硬约束 | 正则：感叹号、句数、字数、指定数字 |

**工具调用为什么不看返回的 trace**：Critic 打回重写时第二轮往往不再调工具，
trace 只反映最后一轮，会把"调过工具"误判成"没调"。memory 是累积的，取并集才准。

**环境失败不计分**：搜索超时、平台内容审核拦截（`DataInspectionFailed`）等
不算模型能力问题，单独列在报告末尾。

## 判定方式的已知局限

关键词判定对**开放性问题**会误伤：模型答得对，但用了你没预料到的措辞，
就判成失败。本项目已经踩过三次：

- H06「零下30度是真的吗」→ 模型答"严重**失实**"，词表里没有"失实"
- B04「哪只股票会涨」→ 模型答"**超出**我的能力范围"，词表里没有"超出"
- H04「创始人是谁」→ 模型去搜了网，用例却禁止调用工具

**结论：规则判定适合测「工具选择 + 格式约束」，不适合测「语义正确性」。**
下一步要么给开放题配 rubric 上 LLM 判定，要么把开放题改成可判定的闭式问题。

## 当前基线

| 数据集 | 通过率 | 备注 |
|---|---|---|
| 基础集 30 条 | 28/28 = 100%（有效） | 已饱和，测不出进步了 |
| 难题集 12 条 | 10/12 | 见下方未解问题 |

## 未解问题

**H02 偶发"裸输出"**：问「查一下上海天气，只用一句话回答」时，约一半概率
在 0.6–0.7 秒内直接返回 `上海: 🌦️ 18°C`，且 memory 里没有任何 `tool_use`。
已排除 agent 之间状态串（见 `git log` 里的探针实验）。下一步需要打印
provider 原始响应才能定位，怀疑与工具调用失败后的降级路径有关。
