# Reference 参考手册

本目录提供工具、错误码与协议等“查表型”信息，适合在：

- 需要了解某个工具的参数与返回结构；
- 需要根据错误码定位问题；
- 需要理解交易日志 / Journal 结构

时使用。

主要文档：

- 插件侧「工具与数据域」总索引：仓库内 `plugins/data_collection/README.md`、`plugins/data_collection/ROADMAP.md`（与 `config/tools_manifest.yaml` / `tool_runner.py` 对照维护）。
- `工具参考手册.md`：主入口，说明工具来源（`config/tools_manifest.yaml`）、分类与使用方式。
- `工具参考手册-速查.md`：按分类列出的工具速查表（工具 ID / 标签 / 一句话说明）。
- `工具参考手册-场景.md`：按使用场景组织的工具组合与示例。
- `工具参考手册-研究涨停回测.md`：与涨停回马枪等研究/回测工具相关的说明。
- `错误码说明.md`：`tool_runner.py` 的标准错误码与典型场景。
- `trading_journal_schema.md`：交易日志 / Journal 的结构定义。
- `limit_up_pullback_default_params.md`：涨停回马枪等策略的默认参数说明。

### 第三方数据源（AKShare）

- `akshare/README.md`：AKShare 接口说明索引（本地镜像，用于查函数与参数）。
- `akshare/AKShare*.md`：按资产类别划分的详细说明（股票 / 指数 / 基金 / 期货 / 期权）。

当你在编写工作流、调试工具或集成其他系统时，优先在此目录中查找权威定义。
