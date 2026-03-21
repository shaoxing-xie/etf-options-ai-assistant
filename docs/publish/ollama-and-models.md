# Ollama 与模型准备

## 为什么关键

本项目部分记忆/嵌入链路依赖本地 Ollama。  
若 Ollama 未就绪，OpenClaw 启动与推理链路可能不稳定。

## 1. 安装与启动（Linux/WSL）

确认服务状态：

```bash
systemctl status ollama.service --no-pager
curl http://127.0.0.1:11434
```

预期：返回 `Ollama is running`。

## 2. 拉取需要的模型

按你的 `openclaw.json` 实际配置拉取模型（示例）：

```bash
ollama pull nomic-embed-text
ollama pull qwen2.5:7b
```

> 以项目当前配置为准，避免文档模型名与运行配置不一致。

## 3. 自检

```bash
curl -s http://127.0.0.1:11434/api/tags
```

预期：可看到模型列表 JSON。

## 4. 常见问题

- `curl 11434` 超时：先检查 `ollama.service` 是否运行
- OpenClaw 启动慢：先确认 Ollama 模型是否已下载完成
- 内存不足：先降级到轻量模型，保证链路可用再升级
