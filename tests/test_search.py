"""搜索层的离线测试（不联网）。

背景：DDGS 在本机实测 12–24 秒，还经常超时；Bing 网页结果 0.5 秒。
所以 search_web 改成「Bing 优先、DDG 兜底」，并加入 TTL 缓存。
这些测试覆盖解析逻辑和降级顺序，全部离线，不依赖网络。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.tools as tools  # noqa: E402

BING_HTML = """
<ol id="b_results">
<li class="b_algo"><h2><a href="https://example.com/a">AI 行业周报</a></h2>
<p>本周大模型领域有三件大事<b>值得关注</b>。</p></li>
<li class="b_algo"><h2><a href="https://example.com/b">国内 AI 政策</a></h2>
<p>相关部门发布了新的管理办法。</p></li>
<li class="b_algo"><h2><a href="https://example.com/c">第三篇</a></h2>
<p>摘要三</p></li>
</ol>
"""


def test_parse_bing_html_extracts_title_body_href():
    items = tools._parse_bing_html(BING_HTML, 3)
    assert len(items) == 3
    assert items[0]["title"] == "AI 行业周报"
    assert items[0]["href"] == "https://example.com/a"
    # 内联标签要被剥掉，但文字保留
    assert "值得关注" in items[0]["body"]
    assert "<b>" not in items[0]["body"]


def test_parse_bing_html_respects_max_results():
    assert len(tools._parse_bing_html(BING_HTML, 2)) == 2


def test_parse_bing_html_handles_empty_page():
    assert tools._parse_bing_html("<html>nothing</html>", 3) == []


def test_search_falls_back_to_ddg_when_bing_fails(monkeypatch):
    """Bing 挂掉时必须降级到 DDG，而不是直接报错。"""
    monkeypatch.setenv("KENDER_SEARCH_PROVIDERS", "bing,ddg")
    monkeypatch.setattr(tools, "_SEARCH_CACHE", {})

    def boom(query, n):
        raise RuntimeError("bing down")

    monkeypatch.setattr(tools, "_do_bing_search", boom)
    monkeypatch.setattr(
        tools, "_do_ddg_search", lambda q, n: [{"title": "兜底结果", "body": "b", "href": "h"}]
    )

    resp = tools.search_web("测试查询")
    text = resp.content[0]["text"]
    assert "兜底结果" in text


def test_search_uses_cache_on_repeat(monkeypatch):
    """同一 query 第二次必须命中缓存，不再打网络。"""
    calls = {"n": 0}

    def fake_bing(query, n):
        calls["n"] += 1
        return [{"title": "结果", "body": "b", "href": "h"}]

    monkeypatch.setenv("KENDER_SEARCH_PROVIDERS", "bing")
    monkeypatch.setattr(tools, "_SEARCH_CACHE", {})
    monkeypatch.setattr(tools, "_do_bing_search", fake_bing)

    tools.search_web("同一个问题")
    tools.search_web("同一个问题")
    assert calls["n"] == 1


def test_search_reports_error_when_all_providers_fail(monkeypatch):
    monkeypatch.setenv("KENDER_SEARCH_PROVIDERS", "bing,ddg")
    monkeypatch.setattr(tools, "_SEARCH_CACHE", {})
    monkeypatch.setattr(tools, "_do_bing_search", lambda q, n: (_ for _ in ()).throw(RuntimeError("b")))
    monkeypatch.setattr(tools, "_do_ddg_search", lambda q, n: (_ for _ in ()).throw(RuntimeError("d")))

    text = tools.search_web("全挂").content[0]["text"]
    assert "搜索出错" in text
