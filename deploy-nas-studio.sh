#!/bin/bash
# 部署控制面容器到 NAS(群晖 ContainerManager)
# 用法: bash deploy-nas-studio.sh [build|token]
#   build  重新构建并重启容器(默认)
#   token  只查看代理 token
set -e
cd "$(dirname "$0")"
DOCKER=/volume1/@appstore/ContainerManager/usr/bin/docker
NAME=studio-console
DATA=/volume1/docker/studio-data

ssh nas "mkdir -p $DATA /volume1/docker/studio-build"

echo "=== 上传控制面文件 ==="
scp src/pipeline_admin.py src/admin.html src/Dockerfile nas:/volume1/docker/studio-build/

if [ "${1:-build}" = "token" ]; then
  ssh nas "[ -f $DATA/.agent-token ] && cat $DATA/.agent-token || echo 'token 尚未生成(容器首次启动后生成)'"
  exit 0
fi

echo "=== NAS 上构建镜像 ==="
ssh nas "$DOCKER build -t studio-console /volume1/docker/studio-build"

echo "=== (重)启动容器 ==="
ssh nas "mkdir -p '/volume1/share/视频/原片库'"
ssh nas "$DOCKER rm -f $NAME 2>/dev/null || true; \
  $DOCKER run -d --name $NAME --restart unless-stopped \
  -p 8766:8766 -v $DATA:/data \
  -v '/volume1/share/视频':/media:ro \
  -e STUDIO_MEDIA=/media -e STUDIO_SOURCE_DIR=原片库 \
  studio-console"

sleep 3
echo "=== 状态 ==="
ssh nas "$DOCKER ps --filter name=$NAME --format '{{.Names}} {{.Status}} {{.Ports}}'"
echo ""
echo "控制面: http://192.168.100.78:8766"
echo "代理 token(配置到 PC 的 STUDIO_TOKEN):"
ssh nas "cat $DATA/.agent-token 2>/dev/null || echo '(首次访问 /api/agent/* 时生成,跑一次本脚本 token 子命令查看)'"
