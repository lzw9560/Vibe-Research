# 后端: Python 3.11 slim + FastAPI/uvicorn
FROM python:3.11-slim AS base
WORKDIR /app
# 安装系统依赖（mootdx 可能需要编译）
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY news_sources.json ./
EXPOSE 8900
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8900"]
