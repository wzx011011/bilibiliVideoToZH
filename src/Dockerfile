FROM python:3.11-slim
WORKDIR /app
# 控制面零三方依赖(纯标准库 HTTP/JSON)
# 保持 src/ 目录结构:pipeline_admin 以 __file__ 推导 ROOT/src 找 admin.html
COPY pipeline_admin.py admin.html /app/src/
ENV STUDIO_MODE=server STUDIO_DATA=/data PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8766
CMD ["python", "src/pipeline_admin.py", "--host", "0.0.0.0"]
