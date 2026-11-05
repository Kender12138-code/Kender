"""Web 端真实往返测试：通过 Gradio 的 HTTP API 发一句话，读回助手回复。

等价于在浏览器里输入、点发送 —— 走的是同一个 `respond` 生成器，
只是把 DOM 操作换成了 HTTP/SSE。
"""
import json
import sys
import time
import urllib.request

for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001, S110
        pass

BASE = "http://127.0.0.1:7860"


def get_json(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    info = get_json("/gradio_api/info")
    names = list(info.get("named_endpoints", {}).keys())
    print("named endpoints:", names)
    if "/respond" not in names:
        print("❌ respond 未暴露为 API，改用页面级验证")
        return 1

    # 第 1 轮：问天气（应当调用 get_weather）
    payload = {"data": ["上海天气怎么样？", [], False, None, None]}
    req = urllib.request.Request(
        BASE + "/gradio_api/call/respond",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        event = json.loads(r.read().decode("utf-8"))
    eid = event["event_id"]
    print("event_id:", eid)

    # 读 SSE 流，取最后一个 completed 事件
    last = None
    t0 = time.time()
    with urllib.request.urlopen(f"{BASE}/gradio_api/call/respond/{eid}", timeout=180) as r:
        buf = []
        event_name = None
        for raw in r:
            line = raw.decode("utf-8").rstrip("\n")
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                buf.append(line.split(":", 1)[1].strip())
            elif line == "":
                if event_name == "complete" and buf:
                    last = json.loads("".join(buf))
                elif event_name == "error" and buf:
                    print("❌ 服务端报错:", "".join(buf)[:500])
                    return 1
                buf = []
                event_name = None
    took = time.time() - t0

    if last is None:
        print("❌ 没收到 complete 事件")
        return 1

    # complete 事件的 data 可能是 {"data": [...]} 也可能直接是输出列表
    data = last.get("data") if isinstance(last, dict) else last
    if not isinstance(data, list):
        print("❌ 无法解析 complete 事件:", str(last)[:200])
        return 1

    chat = data[1] or []
    trace = (data[3] if len(data) > 3 else "") or ""
    msgs = [
        m for m in chat
        if isinstance(m, dict) and m.get("role") == "assistant"
    ]
    reply = msgs[-1]["content"] if msgs else "(无回复)"
    print(f"\n耗时 {took:.1f}s")
    print("助手回复:", reply[:300])
    print("轨迹面板前 200 字:", trace[:200].replace("\n", " / "))
    ok = bool(reply) and "⏳" not in reply and "⚠️" not in reply
    print("\n结果:", "✅ 通过" if ok else "❌ 失败")
    return 0 if ok else 1


sys.exit(main())
