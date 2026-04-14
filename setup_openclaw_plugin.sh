#!/bin/bash
# OpenClaw 交易助手插件快速配置脚本
# 在 Remote-WSL 的 Cursor 终端中执行此脚本
#
# 注意（OpenClaw 2026.4+）：新环境请优先执行 ./scripts/setup_openclaw_option_trading_assistant.sh
# 写入 plugins.load.paths；本脚本偏历史「在 extensions 下建目录/链文件」流程。

set -e

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== OpenClaw 交易助手插件配置脚本 ===${NC}\n"

# 1. 检查环境
echo -e "${YELLOW}步骤1: 检查环境...${NC}"

# 检查 OpenClaw 目录
if [ ! -d "$HOME/.openclaw" ]; then
    echo -e "${RED}错误: OpenClaw 目录不存在: $HOME/.openclaw${NC}"
    echo "请先安装 OpenClaw"
    exit 1
fi

# 检查符号链接（指向当前 WSL 本地 etf-options-ai-assistant 目录）
if [ ! -L "$HOME/etf-options-ai-assistant" ]; then
    echo -e "${YELLOW}警告: 符号链接不存在，正在创建...${NC}"
    ln -s "$PWD" "$HOME/etf-options-ai-assistant"
    echo -e "${GREEN}✓ 符号链接已创建: $HOME/etf-options-ai-assistant -> $PWD${NC}"
fi

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}错误: 未找到 python3${NC}"
    exit 1
fi

echo -e "${GREEN}✓ 环境检查通过${NC}\n"

# 2. 创建插件目录
echo -e "${YELLOW}步骤2: 创建插件目录...${NC}"

PLUGIN_DIR="$HOME/.openclaw/extensions/option-trading-assistant"
mkdir -p "$PLUGIN_DIR"

echo -e "${GREEN}✓ 插件目录已创建: $PLUGIN_DIR${NC}\n"

# 3. 创建 tool_runner.py 符号链接
echo -e "${YELLOW}步骤3: 配置工具运行器...${NC}"

if [ -f "$HOME/etf-options-ai-assistant/tool_runner.py" ]; then
    # 如果已存在，先删除（无论是文件还是符号链接）
    if [ -e "$PLUGIN_DIR/tool_runner.py" ]; then
        echo -e "${YELLOW}  发现已存在的 tool_runner.py，正在删除...${NC}"
        rm -f "$PLUGIN_DIR/tool_runner.py"
    fi
    ln -s "$HOME/etf-options-ai-assistant/tool_runner.py" "$PLUGIN_DIR/tool_runner.py"
    chmod +x "$PLUGIN_DIR/tool_runner.py"
    echo -e "${GREEN}✓ tool_runner.py 符号链接已创建${NC}"
else
    echo -e "${RED}错误: 找不到 tool_runner.py${NC}"
    echo "  路径: $HOME/etf-options-ai-assistant/tool_runner.py"
    exit 1
fi

# 4. 创建 index.ts（如果不存在）
echo -e "\n${YELLOW}步骤4: 配置插件入口文件...${NC}"

if [ ! -f "$PLUGIN_DIR/index.ts" ]; then
    echo -e "${YELLOW}创建 index.ts 文件...${NC}"
    cat > "$PLUGIN_DIR/index.ts" << 'EOF'
import type { OpenClawPluginApi } from "openclaw/plugin-sdk";
import { exec } from "child_process";
import { promisify } from "util";
import * as path from "path";
import * as os from "os";

const execAsync = promisify(exec);

const plugin = {
  id: "option-trading-assistant",
  name: "Option Trading Assistant",
  description: "期权交易助手插件 - 数据采集、分析、通知工具",
  configSchema: {
    type: "object",
    properties: {
      apiBaseUrl: {
        type: "string",
        default: "http://127.0.0.1:5000",
        description: "原系统API基础地址"
      },
      apiKey: {
        type: "string",
        description: "API Key（可选）"
      }
    }
  },
  register(api: OpenClawPluginApi) {
    registerAllTools(api);
    api.logger.info?.("option-trading-assistant: Registered all tools");
  },
};

function registerAllTools(api: OpenClawPluginApi) {
  // 使用符号链接路径
  const homeDir = os.homedir();
  const scriptPath = path.join(homeDir, "etf-options-ai-assistant", "tool_runner.py");
  
  // 注意：这里需要从 ~/etf-options-ai-assistant/index.ts 复制完整的 registerAllTools 函数
  // 由于函数很长，建议手动复制或使用符号链接
  
  api.logger.info?.(`option-trading-assistant: Using script path: ${scriptPath}`);
}

export default plugin;
EOF
    echo -e "${GREEN}✓ index.ts 已创建（需要手动添加工具注册代码）${NC}"
    echo -e "${YELLOW}⚠ 注意: 需要从 ~/etf-options-ai-assistant/index.ts 复制 registerAllTools 函数内容${NC}"
else
    echo -e "${GREEN}✓ index.ts 已存在${NC}"
fi

# 5. 创建 package.json（如果不存在）
if [ ! -f "$PLUGIN_DIR/package.json" ]; then
    cat > "$PLUGIN_DIR/package.json" << 'EOF'
{
  "name": "option-trading-assistant",
  "version": "1.0.0",
  "description": "期权交易助手插件",
  "main": "index.ts",
  "type": "module"
}
EOF
    echo -e "${GREEN}✓ package.json 已创建${NC}"
fi

# 6. 验证配置
echo -e "\n${YELLOW}步骤5: 验证配置...${NC}"

# 检查文件
if [ -L "$PLUGIN_DIR/tool_runner.py" ]; then
    echo -e "${GREEN}✓ tool_runner.py 符号链接正常${NC}"
    echo "  目标: $(readlink -f "$PLUGIN_DIR/tool_runner.py")"
else
    echo -e "${RED}✗ tool_runner.py 符号链接异常${NC}"
fi

# 测试 Python 导入
echo -e "\n${YELLOW}测试 Python 工具运行器...${NC}"
if python3 -c "import sys; sys.path.insert(0, '$HOME/etf-options-ai-assistant'); from tool_runner import TOOL_MAP; print('✓ 工具映射加载成功，共', len(TOOL_MAP), '个工具')" 2>/dev/null; then
    echo -e "${GREEN}✓ Python 工具运行器测试通过${NC}"
else
    echo -e "${YELLOW}⚠ Python 工具运行器测试失败（可能需要安装依赖）${NC}"
fi

# 7. 显示配置摘要
echo -e "\n${GREEN}=== 配置摘要 ===${NC}"
echo "插件目录: $PLUGIN_DIR"
echo "工具运行器: $PLUGIN_DIR/tool_runner.py -> $(readlink -f "$PLUGIN_DIR/tool_runner.py")"
echo "符号链接: $HOME/etf-options-ai-assistant -> $(readlink -f "$HOME/etf-options-ai-assistant")"
echo ""

# 8. 下一步操作提示
echo -e "${YELLOW}=== 下一步操作 ===${NC}"
echo "1. 在 Cursor 中打开: $PLUGIN_DIR/index.ts"
echo "2. 从 ~/etf-options-ai-assistant/index.ts 复制 registerAllTools 函数内容"
echo "3. 更新 scriptPath 为: path.join(os.homedir(), 'etf-options-ai-assistant', 'tool_runner.py')"
echo "4. 重启 OpenClaw Gateway 以加载插件"
echo "5. 验证插件是否已注册: curl http://127.0.0.1:18789/plugins"
echo ""

echo -e "${GREEN}✓ 配置完成！${NC}"
