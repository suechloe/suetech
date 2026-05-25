#!/bin/bash
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "❌ 找不到 .env 文件，请先复制 .env.example 并填写配置"
  exit 1
fi

if [ ! -d .venv ]; then
  echo "📦 创建虚拟环境..."
  python3 -m venv .venv
fi

source .venv/bin/activate

echo "📦 安装依赖..."
pip install -q -r requirements.txt

echo ""
python main.py
