import gradio as gr

with gr.Blocks() as demo:
    gr.HTML('<div style="background:red;color:white;padding:30px;font-size:24px;">TEST RED BOX</div>')
    gr.HTML('<div style="background:blue;color:white;padding:30px;font-size:24px;margin-top:10px;">TEST BLUE BOX</div>')

demo.launch(server_port=7888)
