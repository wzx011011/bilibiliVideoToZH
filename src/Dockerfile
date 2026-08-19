FROM python:3.11-slim
WORKDIR /app
# 控制面零三方依赖(纯标准库 HTTP/JSON)
COPY pipeline_admin.py admin.html ./
ENV STUDIO_MODE=server STUDIO_DATA=/data PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8766
CMD ["python", "pipeline_admin.py", "--host", "0.0.0.0"]
