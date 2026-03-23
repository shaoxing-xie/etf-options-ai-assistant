# WSL 访问 OpenClaw 仓库目录配置指南

> 状态：该文档仅用于说明 WSL2 内如何访问仓库目录。当前推荐直接使用本地 WSL 仓库路径（不依赖宿主机挂载目录），并优先使用 `docs/publish/README.md` 中的发布主线文档。

## 快速设置

### 方法1：使用符号链接（推荐）

在 WSL 中执行：

```bash
# 直接进入仓库目录（仓库通常已位于 WSL 本地路径）
cd /home/xie/etf-options-ai-assistant
ls -la
```

### 方法2：在 Cursor 中直接打开 WSL 路径

1. 在 Cursor 中按 `Ctrl+Shift+P`（或 `Cmd+Shift+P`）
2. 输入 `Remote-WSL: New WSL Window`
3. 选择 `Open Folder`
4. 输入路径：`/home/xie/etf-options-ai-assistant`

### 方法3：使用工作区配置

在 WSL 中创建 `~/.cursor/workspace.json`：

```json
{
  "folders": [
    {
      "path": "/home/xie/etf-options-ai-assistant"
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

- **仓库路径（WSL）**: `/home/xie/etf-options-ai-assistant`

## 常见问题

### 1. 无法访问仓库路径

检查 WSL 配置：
```bash
# 在 WSL 中测试
ls /home/xie/etf-options-ai-assistant
```

如果无法访问，请确认该目录在当前 WSL 环境中确实存在并且具备读取/执行权限（例如运行 `ls -la`）。

### 2. 文件权限问题

文件权限/所有者异常时，请用 `ls -la`、`stat` 检查并确保当前用户可读取该目录。

### 3. 中文路径问题

如果遇到中文路径编码问题，确保：
- WSL 使用 UTF-8 编码
- Cursor 使用 UTF-8 编码

## 验证配置

在 WSL 中执行：

```bash
# 检查目录是否存在
ls -la /home/xie/etf-options-ai-assistant

# 检查符号链接
ls -la /home/xie/etf-options-ai-assistant

# 测试文件访问
cat /home/xie/etf-options-ai-assistant/README.md
```
