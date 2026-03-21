# Getting Started 入门指南

本目录帮助你在最短时间内完成：

1. 环境与依赖检查；
2. 安装本项目及其 OpenClaw 插件；
3. 运行第一个工作流并验证结果。

## 安装前检查清单（含第三方 SKILL）

除本项目代码与插件外，部分“自动盯盘 / 事件哨兵 / 外部信息补全”能力会依赖 OpenClaw 生态中的第三方 SKILL（技能包）。

- 第一次安装建议先阅读：`docs/getting-started/third-party-skills.md`

推荐阅读顺序：

1. `docs/overview/5分钟快速开始指南.md`  
   - 从“环境检查 → 安装插件 → 配置工作流 → 首次运行”一步步带你跑通。
2. `docs/openclaw/OpenClaw配置指南.md`  
   - 如果你需要在多机 / Remote-WSL 环境中部署或排错，可进一步阅读。
3. `docs/openclaw/README_WSL_ACCESS.md` / `REMOTE_WSL_GUIDE.md` / `REMOTE_WSL_QUICK_REF.md`  
   - 针对 Remote-WSL + Cursor 的访问路径与常见问题。

完成以上文档后，你应该能够：

- 在本地创建虚拟环境并安装依赖；
- 将本项目注册为 OpenClaw 插件；
- 在 OpenClaw 中运行至少一个完整的分析 / 信号工作流。
