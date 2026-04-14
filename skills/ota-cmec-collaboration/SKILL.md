---
name: ota_cmec_collaboration
description: CMEC 共享目录、Cursor 与 OpenClaw 谁写谁读；代码维护通道。维护者向。
---

# OTA：CMEC（Cursor × OpenClaw）协作

## 何时使用

- 在 Cursor 与 OpenClaw 之间同步补丁、共享工作区、执行通道排障。

## 规程

1. **读总案**：目录约定、权限与 E2E 验证步骤以实施方案为准。
2. **不越界**：不把 CMEC 目录当生产密钥仓；密钥仍走 `.env` / OpenClaw secret。

## 权威文档

- `docs/openclaw/OpenClaw与Cursor协作代码维护执行通道CMEC实施方案.md`
- `docs/openclaw/CMEC_E2E_TEST.md`
