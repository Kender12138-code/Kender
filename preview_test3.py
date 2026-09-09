import gradio as gr

with open('data/test_empty.html', 'r', encoding='utf-8') as f:
    html_empty = f.read()
with open('data/test_prod.html', 'r', encoding='utf-8') as f:
    html_prod = f.read()

with gr.Blocks() as demo:
    with gr.Row():
        with gr.Column():
            gr.Markdown("### empty state")
            gr.HTML(f'<div class="preview-box" style="border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;min-height:620px;">{html_empty}</div>')
        with gr.Column():
            gr.Markdown("### with product")
            gr.HTML(f'<div class="preview-box" style="border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;min-height:620px;">{html_prod}</div>')

demo.launch(server_port=7890)
