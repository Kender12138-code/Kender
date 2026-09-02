"""
农民电商 Agent智能体核心模块。

基于 Kender 已有的 DashScope(qwen-plus) 调用能力，做一层农产品店铺专用封装：
- 从农民自然语言中提取/更新店铺信息
- 把结构化数据渲染成可交互的电商页面 HTML
- 页面包含：店铺头图、产品卡片、购物车、模拟结算/微信支付二维码

本模块不改动 Kender 原有功能，仅作为新增能力被 farm_shop_app.py 调用。
"""

import json
import os
from collections.abc import AsyncGenerator

from dotenv import load_dotenv
from agentscope.model import DashScopeChatModel

load_dotenv()


def get_model():
    """复用 Kender 的模型配置，保持单一 API Key 来源。"""
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise ValueError("请先设置 DASHSCOPE_API_KEY 环境变量（复制 .env.example 为 .env 并填入 key）")
    return DashScopeChatModel(
        model_name="qwen-plus",
        api_key=api_key,
    )


async def _call_model_text(model, prompt: str) -> str:
    """调用模型并取回完整文本，兼容 DashScopeChatModel 的流式返回。"""
    res = await model(messages=[{"role": "user", "content": prompt}])
    if isinstance(res, AsyncGenerator):
        text = ""
        async for chunk in res:
            content = chunk["content"] if isinstance(chunk, dict) else None
            if isinstance(content, list):
                text = "".join(
                    str(b.get("text", ""))
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
        return text
    content = res["content"] if isinstance(res, dict) else None
    if isinstance(content, list):
        return "".join(
            str(b.get("text", ""))
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return "" if content is None else str(content)


def _parse_json(text: str):
    """剥掉 markdown 代码块，解析 JSON。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[1:-1]).strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except Exception:
        return None


DEFAULT_SHOP_DATA = {
    "shop_name": "农家小店",
    "slogan": "农家自产 · 绿色新鲜 · 产地直发",
    "style": "朴实",
    "products": [],
}


def _call_model_text_sync(prompt: str) -> str:
    """同步调用 DashScope Chat API，返回完整文本。

    用途：ReActAgent 的进程内工具函数必须是同步的，所以提取/更新店铺信息时
    不走 agentscope 的异步 DashScopeChatModel，而直接用 OpenAI 兼容接口。
    """
    from openai import OpenAI

    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise ValueError("DASHSCOPE_API_KEY 未设置")
    client = OpenAI(api_key=api_key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return resp.choices[0].message.content


async def extract_shop_data(user_text: str, model=None) -> dict:
    """从农民的自然语言中提取店铺信息（异步版本，供直接调用）。"""
    if model is None:
        model = get_model()

    prompt = _build_extract_prompt(user_text)
    text = await _call_model_text(model, prompt)
    return _normalize_shop_data(_parse_json(text))


def extract_shop_data_sync(user_text: str) -> dict:
    """从农民的自然语言中提取店铺信息（同步版本，供 ReActAgent 工具调用）。"""
    prompt = _build_extract_prompt(user_text)
    text = _call_model_text_sync(prompt)
    return _normalize_shop_data(_parse_json(text))


def _build_extract_prompt(user_text: str) -> str:
    return f"""你是农产品电商助手。请从农民的话中提取店铺信息，只返回 JSON，不要任何解释。

要求：
- shop_name: 店铺名（可从农产品/地名推断，如"李家果园"）
- slogan: 宣传语（简短，15字以内）
- style: 页面风格，只能从[清新, 朴实, 现代]中选一个
- products: 产品数组，每个产品包含：
    name（产品名称）
    price（数字价格，元）
    unit（单位，如斤/个/箱/公斤）
    stock（库存描述，如"充足"/"50斤"/"只剩20个"）
    description（30字内产品描述）
- 如果信息不完整，用合理默认值填充，price 必须是数字

农民的话：{user_text}

JSON："""


def _normalize_shop_data(data):
    """把 LLM 返回的数据规范化成合法店铺数据结构。"""
    if data is None:
        return DEFAULT_SHOP_DATA.copy()
    merged = DEFAULT_SHOP_DATA.copy()
    merged.update(data)
    if not isinstance(merged.get("products"), list):
        merged["products"] = []
    return merged


async def update_shop_data(shop_data: dict, user_request: str, model=None) -> dict:
    """根据农民的修改要求更新店铺数据（异步版本）。"""
    if model is None:
        model = get_model()

    prompt = _build_update_prompt(shop_data, user_request)
    text = await _call_model_text(model, prompt)
    return _apply_update(shop_data, _parse_json(text))


def update_shop_data_sync(shop_data: dict, user_request: str) -> dict:
    """根据农民的修改要求更新店铺数据（同步版本，供 ReActAgent 工具调用）。"""
    prompt = _build_update_prompt(shop_data, user_request)
    text = _call_model_text_sync(prompt)
    return _apply_update(shop_data, _parse_json(text))


def _build_update_prompt(shop_data: dict, user_request: str) -> str:
    return f"""你是农产品电商助手。当前店铺信息如下，请根据农民的新要求更新，只返回完整 JSON，不要解释。

当前店铺信息：
{json.dumps(shop_data, ensure_ascii=False, indent=2)}

农民的新要求：{user_request}

要求：
- 保留未被修改的字段
- price 必须是数字
- style 只能从[清新, 朴实, 现代]中选
- 如果要求"换一种风格""换个名字""加点产品"等，只做对应修改

JSON："""


def _apply_update(shop_data: dict, data):
    """把 LLM 返回的更新数据合并到原数据中。"""
    if data is None:
        return shop_data
    updated = shop_data.copy()
    updated.update(data)
    if not isinstance(updated.get("products"), list):
        updated["products"] = shop_data.get("products", [])
    return updated


# 风格 -> (页面背景色, 主题色, 卡片背景色, 强调色)
_STYLE_MAP = {
    "清新": ("#e8f5e9", "#2e7d32", "#ffffff", "#43a047"),
    "现代": ("#ffffff", "#1976d2", "#f5f5f5", "#2196f3"),
    "朴实": ("#fff8e1", "#5d4037", "#ffffff", "#8d6e63"),
}


_PRODUCT_ICONS = {
    "苹果": "🍎", "梨": "🍐", "桃": "🍑", "番茄": "🍅", "西红柿": "🍅",
    "黄瓜": "🥒", "茄子": "🍆", "玉米": "🌽", "大米": "🍚", "鸡蛋": "🥚",
    "草莓": "🍓", "葡萄": "🍇", "西瓜": "🍉", "白菜": "🥬", "萝卜": "🥕",
    "土豆": "🥔", "辣椒": "🌶️", "洋葱": "🧅", "蒜": "🧄", "葱": "🥬",
    "南瓜": "🎃", "红薯": "🍠", "花生": "🥜", "蘑菇": "🍄", "蜂蜜": "🍯",
}


def _pick_icon(name: str) -> str:
    for key, icon in _PRODUCT_ICONS.items():
        if key in name:
            return icon
    return "🌾"


def _render_body(shop_data: dict, include_onclick: bool = True) -> str:
    """渲染店铺页面 body 结构（不含 script）。"""
    style = shop_data.get("style", "朴实")
    bg, primary, card_bg, accent = _STYLE_MAP.get(style, _STYLE_MAP["朴实"])
    shop_name = shop_data.get("shop_name", "农家小店")
    slogan = shop_data.get("slogan", "农家自产 · 绿色新鲜 · 产地直发")
    products = shop_data.get("products", [])

    cards = []
    for p in products:
        name = p.get("name", "农产品")
        price = p.get("price", "待定")
        unit = p.get("unit", "斤")
        stock = p.get("stock", "充足")
        desc = p.get("description", "新鲜农家自产")
        icon = _pick_icon(name)
        cards.append(f"""
        <div class="product-card">
            <div class="product-img">{icon}</div>
            <h3>{name}</h3>
            <p class="desc">{desc}</p>
            <div class="price">¥{price}/{unit}</div>
            <div class="stock">库存：{stock}</div>
            <button class="buy-btn" data-name="{name}" data-price="{price}">加入购物车</button>
        </div>
        """)

    cards_html = "\n".join(cards) if cards else (
        '<p style="text-align:center;color:#999;padding:50px 20px;">'
        '请先告诉我你要卖什么，例如：<br>"我家有50斤西红柿，3块钱一斤，想在网上卖"</p>'
    )

    cart_click = 'onclick="toggleCart()"' if include_onclick else ''
    checkout_click = 'onclick="checkout()"' if include_onclick else ''
    qr_click = 'onclick="closeQr(event)"' if include_onclick else ''
    close_click = 'onclick="closeQrBtn()"' if include_onclick else ''

    return f"""
<div class="header">
    <h1>{shop_name}</h1>
    <p>{slogan}</p>
</div>
<div class="container">
    {cards_html}
</div>
<div class="cart" {cart_click}>🛒 购物车</div>
<div class="cart-panel" id="cart-panel">
    <h4>已选商品</h4>
    <div id="cart-list"><div style="color:#999;">空空如也</div></div>
    <div class="total" id="cart-total">合计：¥0</div>
    <button class="checkout-btn" {checkout_click}>去结算</button>
</div>
<div class="qr-modal" id="qr-modal" {qr_click}>
    <div class="qr-box">
        <h3>微信支付</h3>
        <div class="qr-placeholder">💰</div>
        <p style="color:#666;font-size:14px;">模拟收款二维码<br>实际接入需申请微信支付商户号</p>
        <button class="qr-close-btn" {close_click} style="margin-top:10px;padding:8px 18px;border:none;border-radius:6px;background:{primary};color:white;cursor:pointer;">关闭</button>
    </div>
</div>
"""


def _render_body_inline(shop_data: dict, fixed_position: bool = False) -> str:
    """渲染店铺页面 body，所有样式内联到元素 style 属性（Gradio gr.HTML 专用）。

    为什么不用 <style> 标签：Gradio 6 的 gr.HTML 对 <style> 的处理不稳定，
    会出现 fixed 定位元素显示、主体内容不渲染的诡异现象。内联样式 100% 生效。

    Args:
        shop_data: 店铺数据。
        fixed_position: 是否对购物车/面板使用 position:fixed。Gradio 预览里必须传 False，
            否则 Gradio 的 gr.HTML 会只渲染 fixed 元素、主体内容空白。独立 HTML 文件里传 True。

    类名保留（.buy-btn/.cart/.checkout-btn/.qr-modal 等），供 head 注入的购物车 JS 事件委托使用。
    """
    style = shop_data.get("style", "朴实")
    bg, primary, card_bg, accent = _STYLE_MAP.get(style, _STYLE_MAP["朴实"])
    shop_name = shop_data.get("shop_name", "农家小店")
    slogan = shop_data.get("slogan", "农家自产 · 绿色新鲜 · 产地直发")
    products = shop_data.get("products", [])

    cards = []
    for p in products:
        name = p.get("name", "农产品")
        price = p.get("price", "待定")
        unit = p.get("unit", "斤")
        stock = p.get("stock", "充足")
        desc = p.get("description", "新鲜农家自产")
        icon = _pick_icon(name)
        cards.append(
            f'<div style="background:{card_bg};border-radius:14px;padding:16px;box-shadow:0 3px 12px rgba(0,0,0,0.08);">'
            f'<div style="width:100%;height:170px;background:#f0f0f0;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:72px;margin-bottom:14px;">{icon}</div>'
            f'<h3 style="margin:0 0 8px;color:#333;font-size:18px;">{name}</h3>'
            f'<p style="color:#666;font-size:14px;margin:0 0 12px;min-height:40px;line-height:1.4;">{desc}</p>'
            f'<div style="color:#e53935;font-size:22px;font-weight:bold;margin-bottom:6px;">¥{price}/{unit}</div>'
            f'<div style="color:#888;font-size:13px;margin-bottom:14px;">库存：{stock}</div>'
            f'<button class="buy-btn" data-name="{name}" data-price="{price}" '
            f'style="width:100%;padding:11px;border:none;border-radius:9px;background:{primary};color:white;font-size:15px;cursor:pointer;font-weight:600;">加入购物车</button>'
            f'</div>'
        )

    cards_html = "".join(cards) if cards else (
        '<p style="text-align:center;color:#999;padding:50px 20px;">'
        '请先告诉我你要卖什么，例如：<br>"我家有50斤西红柿，3块钱一斤，想在网上卖"</p>'
    )

    return (
        f'<div style="margin:0;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',\'PingFang SC\',\'Microsoft YaHei\',sans-serif;background:{bg};">'
        f'<div style="background:linear-gradient(135deg,{primary},{accent});color:white;padding:36px 24px;text-align:center;">'
        f'<h1 style="margin:0;font-size:34px;letter-spacing:1px;">{shop_name}</h1>'
        f'<p style="margin:12px 0 0;opacity:0.95;font-size:15px;">{slogan}</p>'
        f'</div>'
        f'<div style="max-width:1000px;margin:26px auto;padding:0 16px;display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:18px;">'
        f'{cards_html}'
        f'</div>'
        f'<div class="cart" style="{("position:fixed;right:24px;bottom:24px;z-index:100;" if fixed_position else "position:relative;display:block;text-align:center;margin:24px auto;width:fit-content;")}background:{primary};color:white;padding:16px 22px;border-radius:50px;box-shadow:0 4px 14px rgba(0,0,0,0.18);cursor:pointer;font-weight:600;">🛒 购物车</div>'
        f'<div class="cart-panel" id="cart-panel" style="{("position:fixed;right:24px;bottom:88px;z-index:100;" if fixed_position else "position:relative;display:none;margin:0 auto 24px;width:fit-content;min-width:260px;")}background:white;border-radius:14px;padding:18px;box-shadow:0 4px 20px rgba(0,0,0,0.15);">'
        f'<h4 style="margin:0 0 12px;color:#333;">已选商品</h4>'
        f'<div id="cart-list"><div style="color:#999;">空空如也</div></div>'
        f'<div id="cart-total" style="border-top:1px solid #eee;margin-top:10px;padding-top:10px;font-weight:bold;color:#e53935;">合计：¥0</div>'
        f'<button class="checkout-btn" style="width:100%;margin-top:12px;padding:10px;border:none;border-radius:8px;background:{accent};color:white;font-size:15px;cursor:pointer;">去结算</button>'
        f'</div>'
        f'<div class="qr-modal" id="qr-modal" style="{("position:fixed;top:0;left:0;right:0;bottom:0;z-index:200;" if fixed_position else "position:relative;display:none;margin:24px auto;width:fit-content;")}background:rgba(0,0,0,0.5);display:none;align-items:center;justify-content:center;">'
        f'<div style="background:white;padding:28px;border-radius:16px;text-align:center;max-width:300px;">'
        f'<h3>微信支付</h3>'
        f'<div style="width:180px;height:180px;background:#f5f5f5;border-radius:12px;display:flex;align-items:center;justify-content:center;margin:16px auto;font-size:64px;">💰</div>'
        f'<p style="color:#666;font-size:14px;">模拟收款二维码<br>实际接入需申请微信支付商户号</p>'
        f'<button class="qr-close-btn" style="margin-top:10px;padding:8px 18px;border:none;border-radius:6px;background:{primary};color:white;cursor:pointer;">关闭</button>'
        f'</div>'
        f'</div>'
        f'</div>'
    )


SHOP_CART_SCRIPT = """
(function () {
  let cart = {};
  function deepQuery(root, selector) {
    if (!root || !root.querySelector) return null;
    const el = root.querySelector(selector);
    if (el) return el;
    const all = root.querySelectorAll('*');
    for (const node of all) {
      if (node.shadowRoot) {
        const found = deepQuery(node.shadowRoot, selector);
        if (found) return found;
      }
    }
    return null;
  }
  function updateCartUI() {
    const list = deepQuery(document, '#cart-list');
    const totalEl = deepQuery(document, '#cart-total');
    if (!list || !totalEl) return;
    const keys = Object.keys(cart);
    if (keys.length === 0) {
      list.innerHTML = '<div style="color:#999;">空空如也</div>';
      totalEl.innerText = '合计：¥0';
      return;
    }
    let total = 0;
    list.innerHTML = keys.map(k => {
      const item = cart[k];
      total += item.price * item.qty;
      return '<div class="cart-item"><span>' + k + '</span><span>¥' + item.price + ' × ' + item.qty + '</span></div>';
    }).join('');
    totalEl.innerText = '合计：¥' + total.toFixed(2);
  }
  function addToCart(name, price) {
    if (!cart[name]) cart[name] = {qty: 0, price: price};
    cart[name].qty += 1;
    updateCartUI();
  }
  function toggleCart() {
    const el = deepQuery(document, '#cart-panel');
    if (!el) return;
    // 兼容两种初始态：内联 display:none（预览版）或类样式 display:none（完整版）
    el.style.display = (el.style.display === 'block') ? 'none' : 'block';
  }
  function checkout() {
    if (Object.keys(cart).length === 0) return alert('购物车是空的');
    const modal = deepQuery(document, '#qr-modal');
    if (modal) modal.style.display = 'flex';
  }
  document.addEventListener('click', function (e) {
    const path = e.composedPath ? e.composedPath() : [e.target];
    const target = path[0];
    if (!target || !target.matches) return;
    if (target.matches('.buy-btn')) {
      const name = target.getAttribute('data-name');
      const price = parseFloat(target.getAttribute('data-price'));
      addToCart(name, price);
      const old = target.innerText;
      target.innerText = '已加入 ✓';
      setTimeout(() => target.innerText = old, 800);
    }
    if (target.matches('.cart')) toggleCart();
    if (target.matches('.checkout-btn')) checkout();
    if (target.matches('.qr-modal') && target.id === 'qr-modal') target.style.display = 'none';
    if (target.matches('.qr-close-btn')) {
      const modal = deepQuery(document, '#qr-modal');
      if (modal) modal.style.display = 'none';
    }
  });
})();
"""


def render_html(shop_data: dict) -> str:
    """渲染完整可交互的店铺页面 HTML（含 script），可直接用浏览器打开。"""
    style = shop_data.get("style", "朴实")
    bg, primary, card_bg, accent = _STYLE_MAP.get(style, _STYLE_MAP["朴实"])
    shop_name = shop_data.get("shop_name", "农家小店")

    body = _render_body(shop_data, include_onclick=True)
    script = SHOP_CART_SCRIPT.replace('deepQuery(document,', 'document.querySelector(').replace("deepQuery(document, '#qr-modal')", "document.getElementById('qr-modal')")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{shop_name}</title>
<style>
body {{ margin:0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: {bg}; }}
.header {{ background: linear-gradient(135deg, {primary}, {accent}); color: white; padding: 36px 24px; text-align: center; }}
.header h1 {{ margin: 0; font-size: 34px; letter-spacing: 1px; }}
.header p {{ margin: 12px 0 0; opacity: 0.95; font-size: 15px; }}
.container {{ max-width: 1000px; margin: 26px auto; padding: 0 16px; display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 18px; }}
.product-card {{ background: {card_bg}; border-radius: 14px; padding: 16px; box-shadow: 0 3px 12px rgba(0,0,0,0.08); transition: transform 0.15s; }}
.product-card:hover {{ transform: translateY(-3px); }}
.product-img {{ width: 100%; height: 170px; background: #f0f0f0; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 72px; margin-bottom: 14px; }}
.product-card h3 {{ margin: 0 0 8px; color: #333; font-size: 18px; }}
.desc {{ color: #666; font-size: 14px; margin: 0 0 12px; min-height: 40px; line-height: 1.4; }}
.price {{ color: #e53935; font-size: 22px; font-weight: bold; margin-bottom: 6px; }}
.stock {{ color: #888; font-size: 13px; margin-bottom: 14px; }}
.buy-btn {{ width: 100%; padding: 11px; border: none; border-radius: 9px; background: {primary}; color: white; font-size: 15px; cursor: pointer; font-weight: 600; }}
.buy-btn:hover {{ background: {accent}; }}
.cart {{ position: fixed; right: 24px; bottom: 24px; background: {primary}; color: white; padding: 16px 22px; border-radius: 50px; box-shadow: 0 4px 14px rgba(0,0,0,0.18); cursor: pointer; font-weight: 600; z-index: 100; }}
.cart-panel {{ position: fixed; right: 24px; bottom: 88px; background: white; border-radius: 14px; padding: 18px; box-shadow: 0 4px 20px rgba(0,0,0,0.15); min-width: 260px; display: none; z-index: 100; }}
.cart-panel h4 {{ margin: 0 0 12px; color: #333; }}
.cart-item {{ display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 14px; }}
.total {{ border-top: 1px solid #eee; margin-top: 10px; padding-top: 10px; font-weight: bold; color: #e53935; }}
.checkout-btn {{ width: 100%; margin-top: 12px; padding: 10px; border: none; border-radius: 8px; background: {accent}; color: white; font-size: 15px; cursor: pointer; }}
.qr-modal {{ position: fixed; top:0; left:0; right:0; bottom:0; background: rgba(0,0,0,0.5); display: none; align-items: center; justify-content: center; z-index: 200; }}
.qr-box {{ background: white; padding: 28px; border-radius: 16px; text-align: center; max-width: 300px; }}
.qr-placeholder {{ width: 180px; height: 180px; background: #f5f5f5; border-radius: 12px; display: flex; align-items: center; justify-content: center; margin: 16px auto; font-size: 64px; }}
</style>
</head>
<body>
{body}
<script>
{script}
</script>
</body>
</html>"""


def render_html_preview(shop_data: dict) -> str:
    """渲染给 Gradio 预览用的 HTML（全内联样式，无 fixed 定位，购物车 JS 由 launch(head=...) 注入）。

    关键：Gradio 6 的 gr.HTML 里如果有 position:fixed 元素，会出现"fixed 元素显示、
    主体内容不渲染"的诡异 bug。所以预览版必须传 fixed_position=False，让购物车/面板
    都走文档流；完整交互版仍用 fixed，通过独立 HTML 文件或新窗口打开。
    """
    return _render_body_inline(shop_data, fixed_position=False)


def render_preview_iframe(shop_data: dict, file_path: str = "data/shop_preview.html", height: int = 620) -> str:
    """把完整店铺页面写入文件，并通过 Gradio 的 `/file=` 静态服务嵌入 iframe 预览。

    为什么用文件+iframe：gr.HTML 直接注入的内容出现过"fixed 元素显示、文档流主体空白"的
    渲染异常，且注入的 <script> 一律不执行。iframe 让店铺页跑在独立浏览上下文里；
    用 `/file=` 真实 URL 而不是 srcdoc/data URI，是因为它是 Gradio 原生的静态文件服务，
    稳定性最高、没有长度限制、也不会被浏览器插件拦截。`?t=...` 用于缓存刷新。
    """
    import time

    full_html = render_html(shop_data)
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(full_html)
    return (
        f'<iframe src="/gradio_api/file={file_path}?t={int(time.time() * 1000)}" title="店铺预览" '
        f'style="width:100%;height:{height}px;border:none;border-radius:12px;background:#fff;display:block;"></iframe>'
    )


def generate_reply(shop_data: dict, is_new: bool) -> str:
    """根据当前店铺数据生成一句自然语言回复。"""
    products = shop_data.get("products", [])
    shop_name = shop_data.get("shop_name", "农家小店")

    if not products:
        return '我听到了，但还没搞清楚你要卖什么。可以说详细一点，比如"我家有50斤西红柿，3块钱一斤，想在网上卖"。'

    items = "、".join([f"{p.get('name')} ¥{p.get('price')}/{p.get('unit')}" for p in products])
    action = "已经帮你生成了店铺页面" if is_new else "已经按你的要求更新了页面"
    return (
        f"{action}。当前店铺叫「{shop_name}」，展示了：{items}。\n\n"
        "你可以继续跟我说：\n"
        '- "换个清爽点的风格"\n'
        '- "再加一箱土鸡蛋，60元一箱"\n'
        '- "西红柿改成2块5一斤"'
    )
