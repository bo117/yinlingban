# ============================================================
# 「银龄伴」后端 Dockerfile（角色2：郝英博）
# 构建镜像：
#   docker build -t yinlingban-backend .
# 运行容器：
#   docker run -d -p 8000:8000 --env-file .env yinlingban-backend
# ============================================================

FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 时区设为北京时间
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 先复制依赖清单单独安装（利用 Docker 层缓存，改代码不用重装依赖）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY app/ ./app/
COPY data/ ./data/
COPY templates/ ./templates/
COPY start.py .

# 暴露端口
EXPOSE 8000

# 健康检查（每 30 秒探活一次）
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

# 启动命令（统一用 .py 启动，符合项目规范）
CMD ["python", "start.py"]
