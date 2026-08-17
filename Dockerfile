FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860

# Docker 环境下监听所有网卡，本地开发默认仍是 127.0.0.1
ENV GRADIO_SERVER_NAME=0.0.0.0

CMD ["python", "main.py", "--web"]
