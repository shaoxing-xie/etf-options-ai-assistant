#!/bin/bash
# 设置 WSL 访问 etf-options-ai-assistant 目录的脚本
# 使用方法：在 WSL 中执行 bash setup_wsl_access.sh

set -e

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== 设置 WSL 访问 etf-options-ai-assistant 目录 ===${NC}"

# 方案1：在 WSL 主目录创建符号链接（推荐）
WSL_HOME="$HOME"
LINK_NAME="$WSL_HOME/etf-options-ai-assistant"
TARGET_PATH="$PWD"

echo -e "\n${YELLOW}方案1：创建符号链接${NC}"
if [ -L "$LINK_NAME" ]; then
    echo "符号链接已存在: $LINK_NAME"
    read -p "是否删除并重新创建? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm "$LINK_NAME"
        ln -s "$TARGET_PATH" "$LINK_NAME"
        echo -e "${GREEN}✓ 符号链接已更新: $LINK_NAME -> $TARGET_PATH${NC}"
    fi
elif [ -e "$LINK_NAME" ]; then
    echo -e "${YELLOW}警告: $LINK_NAME 已存在但不是符号链接${NC}"
    read -p "是否备份并创建符号链接? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        mv "$LINK_NAME" "${LINK_NAME}.backup"
        ln -s "$TARGET_PATH" "$LINK_NAME"
        echo -e "${GREEN}✓ 已备份原文件并创建符号链接${NC}"
    fi
else
    ln -s "$TARGET_PATH" "$LINK_NAME"
    echo -e "${GREEN}✓ 符号链接已创建: $LINK_NAME -> $TARGET_PATH${NC}"
fi

# 方案2：在 ~/workspace 目录创建符号链接（可选）
WORKSPACE_DIR="$WSL_HOME/workspace"
if [ ! -d "$WORKSPACE_DIR" ]; then
    mkdir -p "$WORKSPACE_DIR"
    echo -e "${GREEN}✓ 已创建 workspace 目录: $WORKSPACE_DIR${NC}"
fi

WORKSPACE_LINK="$WORKSPACE_DIR/etf-options-ai-assistant"
if [ ! -L "$WORKSPACE_LINK" ]; then
    ln -s "$TARGET_PATH" "$WORKSPACE_LINK"
    echo -e "${GREEN}✓ 工作区符号链接已创建: $WORKSPACE_LINK${NC}"
fi

# 验证访问
echo -e "\n${YELLOW}验证访问权限...${NC}"
if [ -d "$TARGET_PATH" ]; then
    echo -e "${GREEN}✓ 目标目录可访问: $TARGET_PATH${NC}"
    ls -la "$TARGET_PATH" | head -5
else
    echo -e "${YELLOW}⚠ 目标目录不可访问: $TARGET_PATH${NC}"
    echo "请检查："
    echo "  1. Windows 路径是否正确"
    echo "  2. WSL 是否可以访问 /mnt/d/"
    echo "  3. 文件权限是否正确"
fi

# 显示使用说明
echo -e "\n${GREEN}=== 使用说明 ===${NC}"
echo "在 Cursor 中使用 Remote-WSL 时，可以通过以下路径访问："
echo "  1. 主目录符号链接: ~/etf-options-ai-assistant"
echo "  2. 工作区符号链接: ~/workspace/etf-options-ai-assistant"
echo "  3. 完整路径: $TARGET_PATH"
echo ""
echo "在 Cursor 中打开文件夹："
echo "  File -> Open Folder -> ~/etf-options-ai-assistant"
