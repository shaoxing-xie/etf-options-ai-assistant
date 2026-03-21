# OpenClaw 交易助手系统配置指南

**适用环境**: Remote-WSL 的 Cursor + OpenClaw  
**配置位置**: WSL 环境中的 `~/.openclaw/` 目录

> 状态：该文档包含早期实践片段，部分内容已不再是当前权威流程。  
> 请优先阅读并执行：
> - `docs/publish/deployment-openclaw.md`
> - `docs/publish/env-vars.md`
> - `docs/publish/service-ops.md`
> - `docs/publish/plugins-and-skills.md`

---

## 📋 配置前准备

### 1. 确认环境

在 WSL 终端中执行：

```bash
# 检查 OpenClaw 目录
ls -la ~/.openclaw/

# 检查符号链接（如果已创建）
ls -la ~/etf-options-ai-assistant

# 检查 Python 环境
python3 --version
which python3
```

### 2. 确认原系统 API 服务

确保原系统 API 服务正在运行（在 Windows 中）：

```bash
# 在 WSL 中测试 API 连接
curl http://127.0.0.1:5000/api/status
```

如果无法连接，需要在 Windows 中启动 API 服务。

---

## 🚀 第一步：创建 OpenClaw 插件目录结构

在 Remote-WSL 的 Cursor 中打开终端（WSL 环境），执行：

```bash
# 创建插件目录
mkdir -p ~/.openclaw/extensions/option-trading-assistant

# 进入插件目录
cd ~/.openclaw/extensions/option-trading-assistant
```

---

## 📦 第二步：创建插件入口文件

### 2.1 创建 TypeScript 入口文件（index.ts）

在 `~/.openclaw/extensions/option-trading-assistant/` 目录下创建 `index.ts`：

```typescript
import type { OpenClawPluginApi } from "openclaw/plugin-sdk";
import { exec } from "child_process";
import { promisify } from "util";

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
  const scriptPath = "~/etf-options-ai-assistant/tool_runner.py";
  
  // 注册所有工具...
  // （从 etf-options-ai-assistant/index.ts 复制 registerAllTools 函数内容）
}

export default plugin;
```

**注意**：需要从 `~/etf-options-ai-assistant/index.ts` 复制完整的 `registerAllTools` 函数内容。

### 2.2 创建 Python 工具运行器（tool_runner.py）

在 `~/.openclaw/extensions/option-trading-assistant/` 目录下创建 `tool_runner.py`：

```python
#!/usr/bin/env python3
"""
OpenClaw 工具运行器
从符号链接路径导入工具并执行
"""

import sys
import os
from pathlib import Path

# 添加符号链接路径到 Python 路径
symbolic_link_path = Path.home() / "etf-options-ai-assistant"
if symbolic_link_path.exists():
    sys.path.insert(0, str(symbolic_link_path))
    sys.path.insert(0, str(symbolic_link_path / "plugins"))

# 从原系统导入工具映射
from tool_runner import TOOL_MAP, run_tool

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python tool_runner.py <tool_name> [json_params]")
        sys.exit(1)
    
    tool_name = sys.argv[1]
    params_json = sys.argv[2] if len(sys.argv) > 2 else "{}"
    
    result = run_tool(tool_name, params_json)
    print(result)
```

**或者**，直接创建符号链接到原系统的 tool_runner.py：

```bash
# 在 ~/.openclaw/extensions/option-trading-assistant/ 目录下
ln -s ~/etf-options-ai-assistant/tool_runner.py ./tool_runner.py
```

---

## 🔧 第三步：配置插件路径

### 3.1 更新 index.ts 中的路径

在 `index.ts` 中，更新 `scriptPath`：

```typescript
function registerAllTools(api: OpenClawPluginApi) {
  // 使用绝对路径或符号链接路径
  const scriptPath = "/home/xie/.openclaw/extensions/option-trading-assistant/tool_runner.py";
// 或者使用符号链接
// const scriptPath = "~/etf-options-ai-assistant/tool_runner.py";
  
  // ... 注册工具
}
```

### 3.2 确保 tool_runner.py 可执行

```bash
chmod +x ~/.openclaw/extensions/option-trading-assistant/tool_runner.py
```

---

## 📝 第四步：创建插件配置文件

### 4.1 创建 package.json（如果 OpenClaw 需要）

在 `~/.openclaw/extensions/option-trading-assistant/` 目录下创建 `package.json`：

```json
{
  "name": "option-trading-assistant",
  "version": "1.0.0",
  "description": "期权交易助手插件",
  "main": "index.ts",
  "dependencies": {
    "openclaw": "*"
  }
}
```

### 4.2 创建插件元数据文件（如果 OpenClaw 需要）

创建 `plugin.json`：

```json
{
  "id": "option-trading-assistant",
  "name": "Option Trading Assistant",
  "version": "1.0.0",
  "description": "期权交易助手插件 - 数据采集、分析、通知工具",
  "author": "Your Name",
  "entry": "index.ts",
  "config": {
    "apiBaseUrl": {
      "type": "string",
      "default": "http://127.0.0.1:5000",
      "description": "原系统API基础地址"
    }
  }
}
```

---

## ✅ 第五步：验证配置

### 5.1 检查目录结构

```bash
cd ~/.openclaw/extensions/option-trading-assistant
tree -L 2
```

应该看到：
```
.
├── index.ts
├── tool_runner.py
├── package.json (可选)
└── plugin.json (可选)
```

### 5.2 测试 Python 工具运行器

```bash
# 测试工具运行器
python3 ~/.openclaw/extensions/option-trading-assistant/tool_runner.py tool_check_trading_status "{}"
```

### 5.3 检查符号链接

```bash
# 检查符号链接是否正常
ls -la ~/etf-options-ai-assistant
ls -la ~/.openclaw/extensions/option-trading-assistant/tool_runner.py
```

---

## 🔄 第六步：在 OpenClaw 中注册插件

### 6.1 重启 OpenClaw Gateway

```bash
# 如果 OpenClaw Gateway 正在运行，需要重启以加载新插件
# 检查 Gateway 状态
curl http://127.0.0.1:18789/health

# 重启 Gateway（根据实际部署方式）
# 例如：systemctl restart openclaw-gateway
# 或者：pkill -f openclaw && openclaw start
```

### 6.2 验证插件注册

```bash
# 检查插件是否已注册
curl http://127.0.0.1:18789/plugins

# 应该看到 option-trading-assistant 插件
```

---

## 🎯 第七步：配置 Agent（可选）

### 7.1 创建 Agent 配置目录

```bash
mkdir -p ~/.openclaw/agents
```

### 7.2 复制 Agent 配置文件

```bash
# 从符号链接复制 Agent 配置（作为参考）
cp ~/etf-options-ai-assistant/agents/*.yaml ~/.openclaw/agents/

# 或者创建符号链接
ln -s ~/etf-options-ai-assistant/agents ~/.openclaw/agents/trading-assistant
```

**注意**：Agent 配置文件格式可能需要根据 OpenClaw 的实际要求进行调整。

---

## 🐛 故障排查

### 问题1：无法找到工具模块

**错误**：`ModuleNotFoundError: No module named 'plugins'`

**解决**：
```bash
# 检查 Python 路径
python3 -c "import sys; print('\n'.join(sys.path))"

# 确保符号链接路径在 Python 路径中
export PYTHONPATH="$HOME/etf-options-ai-assistant:$PYTHONPATH"
```

### 问题2：API 连接失败

**错误**：`Connection refused` 或 `无法连接到 http://127.0.0.1:5000`

**解决**：
1. 确保原系统 API 服务在 Windows 中运行
2. 在 WSL 中测试连接：
   ```bash
   curl http://127.0.0.1:5000/api/status
   ```
3. 如果失败，检查 Windows 防火墙设置

### 问题3：符号链接路径问题

**错误**：`No such file or directory`

**解决**：
```bash
# 检查符号链接
ls -la ~/etf-options-ai-assistant

# 重新创建符号链接
rm ~/etf-options-ai-assistant
ln -s /mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/etf-options-ai-assistant ~/etf-options-ai-assistant
```

---

## 📚 参考文件

- 插件代码：`~/etf-options-ai-assistant/index.ts`
- 工具运行器：`~/etf-options-ai-assistant/tool_runner.py`
- Agent 配置：`~/etf-options-ai-assistant/agents/`
- 详细文档：`~/etf-options-ai-assistant/插件集成到OpenClaw指南.md`

---

## ✅ 配置检查清单

- [ ] OpenClaw 目录存在：`~/.openclaw/extensions/`
- [ ] 插件目录已创建：`~/.openclaw/extensions/option-trading-assistant/`
- [ ] `index.ts` 文件已创建并配置正确
- [ ] `tool_runner.py` 文件已创建或符号链接已建立
- [ ] 符号链接 `~/etf-options-ai-assistant` 正常工作
- [ ] Python 路径配置正确
- [ ] 原系统 API 服务正在运行
- [ ] OpenClaw Gateway 已重启并加载插件
- [ ] 插件在 OpenClaw 中可见并可调用

---

完成以上步骤后，交易助手系统的插件应该已经在 OpenClaw 中配置完成，可以在 OpenClaw 的工作流中使用所有工具了。
