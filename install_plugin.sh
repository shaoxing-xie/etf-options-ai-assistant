#!/bin/bash
# 自动安装脚本
# 用于自动安装option-trading-assistant插件到OpenClaw

set -e  # 遇到错误立即退出

# 颜色输出
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_SOURCE_DIR="$SCRIPT_DIR"
OPENCLAW_HOME="$HOME/.openclaw"
PLUGIN_TARGET_DIR="$OPENCLAW_HOME/extensions/option-trading-assistant"

echo "============================================================"
echo "OpenClaw插件自动安装脚本"
echo "============================================================"
echo "插件源目录: $PLUGIN_SOURCE_DIR"
echo "插件目标目录: $PLUGIN_TARGET_DIR"
echo ""

# 步骤1：检查前置条件
print_info "步骤1: 检查前置条件..."

# 检查Python
if ! command -v python3 &> /dev/null; then
    print_error "Python3未安装，请先安装Python 3.8+"
    exit 1
fi
print_success "Python3已安装: $(python3 --version)"

# 检查OpenClaw目录
if [ ! -d "$OPENCLAW_HOME" ]; then
    print_warning "OpenClaw目录不存在: $OPENCLAW_HOME"
    print_info "创建OpenClaw目录..."
    mkdir -p "$OPENCLAW_HOME/extensions"
fi
print_success "OpenClaw目录存在"

# 步骤2：创建插件目录
print_info "步骤2: 创建插件目录..."
mkdir -p "$PLUGIN_TARGET_DIR/plugins"
print_success "插件目录创建成功: $PLUGIN_TARGET_DIR"

# 步骤3：创建符号链接
print_info "步骤3: 创建符号链接..."

cd "$PLUGIN_TARGET_DIR/plugins"

# 删除已存在的符号链接（如果存在）
for dir in data_collection analysis notification data_access utils; do
    if [ -L "$dir" ] || [ -d "$dir" ]; then
        rm -rf "$dir"
    fi
done

# 创建符号链接
ln -sf "$PLUGIN_SOURCE_DIR/plugins/data_collection" ./data_collection
ln -sf "$PLUGIN_SOURCE_DIR/plugins/analysis" ./analysis
ln -sf "$PLUGIN_SOURCE_DIR/plugins/notification" ./notification
ln -sf "$PLUGIN_SOURCE_DIR/plugins/data_access" ./data_access
ln -sf "$PLUGIN_SOURCE_DIR/plugins/utils" ./utils

print_success "符号链接创建成功"

# 验证符号链接
for dir in data_collection analysis notification data_access utils; do
    if [ -L "$dir" ] && [ -e "$dir" ]; then
        print_success "  $dir -> $(readlink -f "$dir")"
    else
        print_error "  $dir 符号链接创建失败"
        exit 1
    fi
done

# 步骤4：复制配置文件
print_info "步骤4: 复制配置文件..."

cd "$PLUGIN_TARGET_DIR"

# 复制插件入口文件（如果存在）
if [ -f "$PLUGIN_SOURCE_DIR/index.ts" ]; then
    cp "$PLUGIN_SOURCE_DIR/index.ts" ./index.ts
    print_success "插件入口文件复制成功"
fi

# 复制工具运行脚本（如果存在）
if [ -f "$PLUGIN_SOURCE_DIR/tool_runner.py" ]; then
    cp "$PLUGIN_SOURCE_DIR/tool_runner.py" ./tool_runner.py
    chmod +x ./tool_runner.py
    print_success "工具运行脚本复制成功"
fi

# 创建package.json（如果不存在）
if [ ! -f "package.json" ]; then
    cat > package.json <<EOF
{
  "name": "option-trading-assistant",
  "version": "1.0.0",
  "description": "期权交易助手OpenClaw插件",
  "main": "index.ts",
  "scripts": {
    "test": "echo \"Error: no test specified\" && exit 1"
  },
  "keywords": ["openclaw", "trading", "option"],
  "author": "",
  "license": "MIT"
}
EOF
    print_success "package.json创建成功"
fi

# 创建openclaw.plugin.json（如果不存在）
if [ ! -f "openclaw.plugin.json" ]; then
    cat > openclaw.plugin.json <<EOF
{
  "name": "option-trading-assistant",
  "version": "1.0.0",
  "description": "期权交易助手插件",
  "main": "index.ts",
  "author": "",
  "license": "MIT"
}
EOF
    print_success "openclaw.plugin.json创建成功"
fi

# 步骤5：安装Python依赖
print_info "步骤5: 安装Python依赖..."

REQUIRED_PACKAGES=("pandas" "numpy" "requests" "akshare")
OPTIONAL_PACKAGES=("psutil")

for package in "${REQUIRED_PACKAGES[@]}"; do
    if python3 -c "import $package" 2>/dev/null; then
        print_success "  $package 已安装"
    else
        print_info "  安装 $package..."
        pip3 install "$package" --quiet
        print_success "  $package 安装成功"
    fi
done

for package in "${OPTIONAL_PACKAGES[@]}"; do
    if python3 -c "import $package" 2>/dev/null; then
        print_success "  $package 已安装（可选）"
    else
        print_warning "  $package 未安装（可选，用于资源监控）"
    fi
done

# 步骤6：验证安装
print_info "步骤6: 验证安装..."

# 检查关键文件
KEY_FILES=("plugins/data_collection" "plugins/analysis" "plugins/notification" "plugins/data_access" "plugins/utils")
ALL_EXIST=true

for key_file in "${KEY_FILES[@]}"; do
    if [ -e "$PLUGIN_TARGET_DIR/$key_file" ]; then
        print_success "  $key_file 存在"
    else
        print_error "  $key_file 不存在"
        ALL_EXIST=false
    fi
done

if [ "$ALL_EXIST" = false ]; then
    print_error "安装验证失败"
    exit 1
fi

# 步骤7：提示重启Gateway
print_info "步骤7: 完成安装"
print_success "插件安装完成！"
echo ""
print_info "下一步操作："
echo "  1. 重启OpenClaw Gateway:"
echo "     sudo systemctl restart openclaw-gateway"
echo ""
echo "  2. 检查插件注册状态:"
echo "     openclaw status"
echo "     或访问 Dashboard: http://127.0.0.1:18789/"
echo ""
echo "  3. 测试工具:"
echo "     在Dashboard中找到 option-trading-assistant 插件"
echo "     测试工具: tool_check_trading_status"
echo ""
print_info "详细说明请参考: 5分钟快速开始指南.md"
