#!/bin/bash
# ==============================================================================
# Dify on WeChat + Gewechat 一键部署脚本
# 适用环境: 阿里云杭州 ECS, 已安装 Docker / docker-compose(或 docker compose 插件)
# 使用方法:   bash deploy.sh
# ==============================================================================
set -e

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DEPLOY_DIR"

echo "============================================================"
echo "  Dify on WeChat (gewechat通道) 一键部署"
echo "  部署目录: $DEPLOY_DIR"
echo "============================================================"

# ---------- 1. 检查 Docker ----------
echo "[1/6] 检查 Docker 环境..."
if ! command -v docker &>/dev/null; then
    echo "未检测到 Docker, 开始自动安装..."
    curl -fsSL https://get.docker.com | bash
    systemctl enable docker
    systemctl start docker
fi
docker --version

# 检查 docker compose (v2 插件 或 docker-compose v1)
COMPOSE_CMD=""
if docker compose version &>/dev/null; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &>/dev/null; then
    COMPOSE_CMD="docker-compose"
else
    echo "未检测到 docker compose, 正在安装 docker compose 插件..."
    apt-get update -y && apt-get install -y docker-compose-plugin || \
        curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
        -o /usr/local/bin/docker-compose && chmod +x /usr/local/bin/docker-compose
    if docker compose version &>/dev/null; then
        COMPOSE_CMD="docker compose"
    else
        COMPOSE_CMD="docker-compose"
    fi
fi
echo "使用 Compose 命令: $COMPOSE_CMD"

# ---------- 2. 拉取 Gewechat 镜像 ----------
echo "[2/6] 拉取 Gewechat 镜像(阿里云镜像源)..."
if ! docker image inspect gewe &>/dev/null; then
    docker pull registry.cn-chengdu.aliyuncs.com/tu1h/wechotd:alpine
    docker tag registry.cn-chengdu.aliyuncs.com/tu1h/wechotd:alpine gewe
else
    echo "gewe 镜像已存在,跳过拉取"
fi

# ---------- 3. 准备目录 ----------
echo "[3/6] 创建数据/插件目录..."
mkdir -p "$DEPLOY_DIR/gewechat/data"
mkdir -p "$DEPLOY_DIR/plugins"
chmod 666 "$DEPLOY_DIR/config.json" 2>/dev/null || true

# ---------- 4. 阿里云安全组提示 ----------
echo "[4/6] 端口/安全组检查提醒..."
echo "  请确认阿里云 ECS 安全组已放行以下端口: 2531, 2532, 9919(机器人回调), 7860(Web UI,可选)"
echo "  如未放行, 请在阿里云控制台 -> 安全组 -> 入方向规则中放行 TCP 端口。"
echo ""

# ---------- 5. 启动服务 ----------
echo "[5/6] 启动 docker compose 服务..."
$COMPOSE_CMD up -d

echo ""
echo "[6/6] 等待服务就绪..."
sleep 5

echo "============================================================"
echo "  部署完成! 服务状态:"
echo "============================================================"
$COMPOSE_CMD ps
echo ""
echo "============================================================"
echo "  后续步骤:"
echo "============================================================"
echo "1. 查看登录二维码:"
echo "     docker logs -f dify-on-wechat"
echo "   看到二维码链接后, 用你要登录的微信扫码 (微信账号和服务器必须在浙江省/同省!)"
echo ""
echo "2. token 和 app_id 会自动写入 config.json, 无需手动填写"
echo ""
echo "3. 常用命令:"
echo "     查看日志:    docker logs -f dify-on-wechat"
echo "     查看gewe:    docker logs -f gewe"
echo "     停止服务:    $COMPOSE_CMD down"
echo "     重启服务:    $COMPOSE_CMD restart"
echo "     更新镜像:    $COMPOSE_CMD pull && $COMPOSE_CMD up -d"
echo ""
echo "4. 注意事项:"
echo "   - gewechat 要求登录微信的手机与服务器在同一省(浙江省)"
echo "   - 仅供个人学习使用, 禁止商业用途"
echo "   - 首次登录成功后 config.json 中的 gewechat_token/app_id 会被自动回填"
echo "============================================================"
