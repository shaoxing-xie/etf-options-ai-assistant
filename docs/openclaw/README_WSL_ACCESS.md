# WSL 访问 OpenClaw_migration 目录配置指南

> 状态：本文档主要保留历史 Remote-WSL 路径访问方式（含 `/mnt/d/...` 示例）。  
> 当前推荐以仓库路径为准（如 `/home/xie/etf-options-ai-assistant`），并优先使用 `docs/publish/README.md` 中的发布主线文档。

## 快速设置

### 方法1：使用符号链接（推荐）

在 WSL 中执行：

```bash
# 进入 WSL
wsl

# 创建符号链接到主目录
ln -s /mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/etf-options-ai-assistant ~/etf-options-ai-assistant

# 验证
ls -la ~/etf-options-ai-assistant
```

### 方法2：在 Cursor 中直接打开 WSL 路径

1. 在 Cursor 中按 `Ctrl+Shift+P`（或 `Cmd+Shift+P`）
2. 输入 `Remote-WSL: New WSL Window`
3. 选择 `Open Folder`
4. 输入路径：`/mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/etf-options-ai-assistant`

### 方法3：使用工作区配置

在 WSL 中创建 `~/.cursor/workspace.json`：

```json
{
  "folders": [
    {
      "path": "/mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/etf-options-ai-assistant"
    }
  ],
  "settings": {
    "files.watcherExclude": {
      "**/node_modules/**": true,
      "**/.git/**": true
    }
  }
}
```

## 路径说明

- **Windows 路径**: `D:\Ubuntu应用环境配置\mcp\option_trading_assistant\etf-options-ai-assistant`
- **WSL 路径**: `/mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/etf-options-ai-assistant`
- **符号链接路径**: `~/etf-options-ai-assistant`（推荐使用）

## 常见问题

### 1. 无法访问 /mnt/d/

检查 WSL 配置：
```bash
# 在 WSL 中测试
ls /mnt/d/
```

如果无法访问，在 Windows PowerShell 中执行：
```powershell
wsl --list --verbose
```

### 2. 文件权限问题

Windows 文件在 WSL 中可能显示为 `drwxrwxrwx`，这是正常的。

### 3. 中文路径问题

如果遇到中文路径编码问题，确保：
- WSL 使用 UTF-8 编码
- Cursor 使用 UTF-8 编码

## 验证配置

在 WSL 中执行：

```bash
# 检查目录是否存在
ls -la /mnt/d/Ubuntu应用环境配置/mcp/option_trading_assistant/etf-options-ai-assistant

# 检查符号链接
ls -la ~/etf-options-ai-assistant

# 测试文件访问
cat ~/etf-options-ai-assistant/README.md
```
