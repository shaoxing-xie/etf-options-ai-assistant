# 第三方插件与技能（Skills）说明

## 目标

明确“必须安装”和“可选增强”，避免因为技能缺失导致能力不一致。

## 1. 必须项（建议首发最小集）

- OpenClaw 基础运行能力（gateway/node）
- 本项目插件：`option-trading-assistant`
- 通知通道（至少一种）：Feishu 或 DingTalk

## 2. 建议项（能力增强）

- `tavily-search`：外部信息检索与事件补全
- `topic-monitor`：主题监控（如已采用）
- `qmd-cli` / 记忆相关技能：研究上下文沉淀

## 3. 安装/校验建议

先看技能清单：

- `docs/getting-started/third-party-skills.md`

安装后验收：

- `openclaw doctor` 中插件/skills 无报错
- 关键工作流可完整跑通（含通知）

## 4. 发布建议

- 在 README 中公开“最小依赖集合”
- 第三方技能版本尽量固定，减少漂移
- 升级技能后执行一次回归检查（至少跑 1 条主工作流）
