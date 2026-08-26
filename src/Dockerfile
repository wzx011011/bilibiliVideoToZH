FROM python:3.11-slim
WORKDIR /app
# 控制面依赖极简:发布模块需要 requests(HTTP)与 segno(二维码)
RUN pip install --no-cache-dir "requests>=2.32,<3" "segno>=1.6,<2"
# 保持 src/ 目录结构:pipeline_admin 以 __file__ 推导 ROOT/src 找 admin.html
COPY pipeline_admin.py publish_module.py admin.html /app/src/
ENV STUDIO_MODE=server STUDIO_DATA=/data PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8766
CMD ["python", "src/pipeline_admin.py", "--host", "0.0.0.0"]
