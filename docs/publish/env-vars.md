# 环境变量配置规范（项目级 + 平台级）

## 分层原则（必须执行）

- `ETF_*`：项目业务变量（数据源、策略参数、项目通知）
- `OPENCLAW_*`：平台变量（gateway、渠道凭据、模型平台）

不要混用，不要把真实密钥写进仓库文件。

## 推荐文件

- 仓库模板：`.env.example`（仅占位）
- 本地运行：`.env`（不提交）
- OpenClaw 平台：`~/.openclaw/.env`（不提交）

## 最小必填（示例）

```bash
# 项目层
ETF_APP_ENV=dev
ETF_TUSHARE_TOKEN=

# 平台层
OPENCLAW_GATEWAY_TOKEN=
OPENCLAW_GATEWAY_PORT=18789
OPENCLAW_OPENROUTER_API_KEY=
```

## 检查命令

```bash
# 加载环境变量后执行
set -a; source ~/.openclaw/.env; set +a
openclaw gateway status
```

若出现 token mismatch，优先确认：

1. 当前 shell 是否已 `source ~/.openclaw/.env`
2. systemd service 是否配置 `EnvironmentFile`
3. `openclaw.json` 与 `.env` 的 token 是否一致
