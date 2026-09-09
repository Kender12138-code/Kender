import gradio as gr

with open('data/render_no_fixed.html', 'r', encoding='utf-8') as f:
    html = f.read()

with gr.Blocks(css=".preview-box { border: 1px solid #e5e7eb; border-radius: 12px; overflow: hidden; height: 100%; min-height: 620px; }") as demo:
    gr.HTML(f'<div class="preview-box">{html}</div>')

demo.launch(server_port=7889)
