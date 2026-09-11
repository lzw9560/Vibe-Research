# 后端: Python 3.14 slim + FastAPI/uvicorn（匹配 .venv 3.14，baostock/akshare/lightgbm 兼容）
FROM python:3.14-slim AS base
WORKDIR /app
# 系统依赖（lightgbm/catboost 可能需 gcc 编译）
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
# Clear pip cache 避免 stale hash mismatch
RUN pip cache purge 2>/dev/null || true && rm -rf /root/.cache/pip/* 2>/dev/null || true
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# VR_DATA_DIR 数据目录（.vibe-research/ 持久化卷，DB 统一 + baostock cache）
ENV VR_DATA_DIR=/app/.vibe-research
RUN mkdir -p $VR_DATA_DIR
EXPOSE 8900
# 生产无 --reload；scheduler cron 内嵌 lifespan（S184 方案 0 数据就绪预检 + cron 17:15）
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8900"]
