# 涨停回马枪策略 - 推荐默认参数与敏感性

## 推荐默认参数（RECOMMENDED_DEFAULT_PARAMS）

基于回测与风控平衡（计划 3.4），当前推荐默认如下：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| sector_score_min | 70 | 板块热度下限，仅参与热度≥70 的板块龙头 |
| hold_days | 5 | 最大持仓天数 |
| stop_loss_below_limit_pct | 5.0 | 止损：跌破涨停价 -5% 或涨停日最低价（取更近者） |
| target_pct | 5.0 | 目标涨幅（相对涨停价）% |
| dip_open_pct_min | -5.0 | 次日低吸：低开幅度下限 -5% |
| dip_open_pct_max | -2.0 | 次日低吸：低开幅度上限 -2% |

## 参数敏感性

- 回调幅度、持仓天数、止损区间、板块热度阈值等可通过 **tool_backtest_limit_up_sensitivity** 做网格搜索。
- 综合得分公式：`胜率*0.5 + max(0, 平均盈亏%)*0.3 - |最大回撤%|*0.2`，取得分最高的一组为推荐参数。
- 网格默认：sector_score_min [60,70,80]、hold_days [3,5,7]、stop_loss_below_limit_pct [3,5,8]、target_pct [3,5,8]。

## 回测指标

- 胜率、平均盈亏、盈亏比(profit_factor)、最大回撤、交易次数、持仓分布(hold_days_dist)。
- 龙头 vs 跟风：当前实现仅做龙头候选，跟风分组可后续扩展。

## 使用方式

```bash
# 回测
python3 tool_runner.py tool_backtest_limit_up_pullback '{"start_date":"20260301","end_date":"20260331"}'

# 参数敏感性（需足够多日数据）
python3 tool_runner.py tool_backtest_limit_up_sensitivity '{"start_date":"20260301","end_date":"20260331"}'
```
