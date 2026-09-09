"""长期记忆抽取的回归测试（无需联网、不调真实模型）。

背景（2026-09-09 修的 bug）：
    只要用户说出名字（"我叫XX"），旧代码会在正则命中后直接 `return name, []`，
    导致本轮的事实/偏好整轮被丢弃 —— 表现为"Kender 记不住东西"。
    这里用假模型把这条路径钉死，防止再次退化。
"""
import asyncio

from src.agent import _extract_user_info


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    """模拟 DashScopeChatModel：记录收到的 prompt，返回预设 JSON。"""

    def __init__(self, reply_json):
        self.reply_json = reply_json
        self.prompts = []

    async def __call__(self, messages, **kwargs):
        self.prompts.append(messages[0]["content"])

        async def gen():
            yield {"content": [{"type": "text", "text": self.reply_json}]}

        return gen()


def test_说出名字时_事实也要被抽到():
    """回归用例：命中"我叫XX"不能把本轮事实一起丢掉。"""
    model = _FakeModel('{"name": "李四", "facts": ["下周三去深圳出差", "不吃香菜"]}')

    name, facts = asyncio.run(
        _extract_user_info(model, "我叫李四，我下周三要去深圳出差", "好的", [])
    )

    assert name == "李四"
    assert facts == ["下周三去深圳出差", "不吃香菜"]
    # 关键断言：必须真的调用了 LLM 做事实抽取，而不是提前 return
    assert len(model.prompts) == 1


def test_模型抽取失败时_正则命中的名字仍然保住():
    model = _FakeModel("这不是合法 JSON")

    name, facts = asyncio.run(
        _extract_user_info(model, "我叫王五，我明天要去体检", "好的", [])
    )

    assert name == "王五"
    assert facts == []


def test_没有新信息时返回空():
    model = _FakeModel('{"name": null, "facts": []}')

    name, facts = asyncio.run(_extract_user_info(model, "今天天气不错", "是的", []))

    assert name is None
    assert facts == []
