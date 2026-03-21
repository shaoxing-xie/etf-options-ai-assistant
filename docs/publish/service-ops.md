# OpenClaw 服务启停与排障

## 1. 推荐重启方式

```bash
set -a; source ~/.openclaw/.env; set +a
~/scripts/restart-openclaw-services.sh
```

该脚本会：

- 停止旧服务并清理残留
- 启动 gateway 后做健康检查
- 启动 node 并给出日志摘要

## 2. 最小健康检查

```bash
ss -ltnp | grep 18789 || true
openclaw gateway status
openclaw doctor --non-interactive
```

通过标准：

- 18789 监听
- `RPC probe: ok`
- doctor 无阻断性错误

## 3. 高频故障与定位

### A. token mismatch

- 现象：`gateway token mismatch`
- 处理：
  1. `source ~/.openclaw/.env`
  2. 检查 `EnvironmentFile` 是否配置到 systemd unit

### B. gateway unreachable / ECONNREFUSED

- 先看端口是否监听：`ss -ltnp | grep 18789`
- 再看服务状态：`systemctl --user status openclaw-gateway.service`
- 最后看日志：`journalctl --user -u openclaw-gateway.service -n 200 --no-pager`

### C. 模型/计费问题

- 现象：`billing error` / `404 model`
- 处理：
  - 校验 `openclaw.json` provider 与 model id
  - 走 `config/model_routes.json` 统一更新流程

## 4. 发布日建议

- 变更后至少观察 10-30 分钟
- 不在观察期内叠加多项配置改动
- 先保证链路可用，再做策略优化
