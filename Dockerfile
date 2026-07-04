FROM python:3.11-slim

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 安装 yt-dlp
RUN pip install --no-cache-dir yt-dlp

WORKDIR /app

# 安装 Python 依赖
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# 复制项目文件
COPY backend/ backend/
COPY frontend/ frontend/

# 创建 videos 目录
RUN mkdir -p videos

EXPOSE 5000

CMD gunicorn --chdir backend app:app --bind 0.0.0.0:${PORT:-5000} --timeout 300 --workers 2
