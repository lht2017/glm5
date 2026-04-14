#!/bin/bash
# GLM Coding Plan Max 季卡抢购工具 - 一键启动脚本
# 使用方法: bash run.sh

cd "$(dirname "$0")"

echo "============================================"
echo " GLM Coding Plan Max 季卡抢购工具"
echo "============================================"

# 检查Python版本
if command -v python3 &>/dev/null; then
    PY=python3
elif command -v python &>/dev/null; then
    PY=python
else
    echo "[错误] 未找到Python，请先安装Python 3.8+"
    exit 1
fi

echo "[INFO] Python: $($PY --version)"

# 安装依赖
echo "[INFO] 检查并安装依赖..."
$PY -m pip install -r requirements.txt -q

# 启动
echo "[INFO] 启动Web服务..."
$PY app.py
