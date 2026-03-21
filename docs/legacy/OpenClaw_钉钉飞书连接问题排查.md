# OpenClaw 钉钉/飞书连接问题排查

## 现象

日志中出现以下信息：

1. **TERMINATE SOCKET: Ping Pong does not transfer heartbeat within heartbeat intervall**  
   - 约每 8 秒出现一次  
   - 表示 WebSocket 连接在心跳超时内未收到 ping/pong 响应

2. **DingTalk Connection attempt X/10 failed: Request failed with status code 502**  
   - 钉钉 Stream API 返回 502 Bad Gateway  
   - 通常为钉钉服务端临时故障

3. **health-monitor: restarting (reason: stale-socket)**  
   - 健康检查发现连接已“僵死”，自动重启渠道客户端  
   - 属于预期恢复机制

---

## 原因分析

| 现象 | 可能原因 |
|------|----------|
| Ping Pong 超时 | 网络不稳定、延迟高、WSL2 网络转发、VPN/代理 |
| 502 错误 | 钉钉/飞书服务端临时故障，非本地配置问题 |
| stale-socket | 上述问题导致连接断开，健康检查触发重启 |

---

## 已做配置调整

在 `openclaw.json` 的 `gateway` 中增加：

```json
"channelHealthCheckMinutes": 10
```

- **默认**：5 分钟  
- **当前**：10 分钟  
- **作用**：降低健康检查频率，减少在短暂网络波动时的频繁重启，给钉钉/飞书 SDK 的自重连更多时间。

---

## 建议排查步骤

1. **网络环境**
   - 若在 WSL2 下运行，可尝试关闭 VPN 或代理后重试  
   - 检查本机到钉钉/飞书 API 的网络延迟和稳定性

2. **钉钉/飞书服务状态**
   - 访问钉钉开放平台、飞书开放平台公告，确认是否有故障或维护  
   - 502 多为服务端问题，一般会自行恢复

3. **验证恢复**
   - 日志中出现 `DingTalk Stream client connected successfully` 或 `Reconnection successful` 表示已恢复  
   - 可用 `openclaw status --deep` 检查各渠道连接状态

4. **若问题持续**
   - 可尝试 `openclaw gateway restart` 重启网关  
   - 或临时将 `channelHealthCheckMinutes` 设为 `0` 关闭自动健康检查（不推荐长期使用）

---

## 参考

- OpenClaw Gateway Health: `gateway.channelHealthCheckMinutes`（默认 5，0 表示禁用）  
- 钉钉 Stream 模式：使用 WebSocket + ping/pong 保活，超时后会关闭连接并尝试重连
