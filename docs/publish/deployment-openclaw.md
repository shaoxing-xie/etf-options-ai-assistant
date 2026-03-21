# OpenClaw 部署本交易助手（主线）

## 目标

在 OpenClaw 中稳定部署 A股/ETF 交易助手，完成以下能力闭环：

- 工具可调用
- 工作流可运行
- 通知可达
- 日志可追踪

## 1. 部署前检查

- 已安装 OpenClaw（建议 `2026.3.x` 或以上）
- Python 环境可用（建议 venv）
- 项目代码可读写
- 已准备 `.env`（见 `env-vars.md`）
- 已确认 Ollama 服务可访问（见 `ollama-and-models.md`）

## 2. 插件接入（本项目插件）

在项目根目录执行：

```bash
bash install_plugin.sh
```

预期结果：

- 在 `~/.openclaw/extensions/` 下可见 `option-trading-assistant`
- OpenClaw 能加载对应插件入口

## 3. 路由与配置同步

如有模型路由配置更新，执行：

```bash
python3 scripts/sync_openclaw_model_routes.py
```

## 4. 服务启动与健康检查

推荐使用统一脚本：

```bash
set -a; source ~/.openclaw/.env; set +a
~/scripts/restart-openclaw-services.sh
```

最小健康标准：

- `openclaw gateway status` 显示 `RPC probe: ok`
- `ss -ltnp | grep 18789` 可见监听
- 通知渠道至少一个可用

## 5. 首次验收用例

- 触发一个盘后分析或信号工作流
- 检查日志输出与通知到达
- 确认无 token mismatch / gateway unreachable
