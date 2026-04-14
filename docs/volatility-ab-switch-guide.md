# 波动引擎 A/B 切换说明

本文档说明如何在今晚快速切换 `fusion / hybrid / garch` 三套生产模板，并在异常时一键回滚。

## 1. 配置位置

- 主配置：合并后配置（域文件：`config/domains/analytics.yaml`）
- 关键节点：`volatility_engine.ab_test`
  - `active_profile`: 当前实验模板
  - `emergency_rollback_to_fusion`: 紧急回滚开关
  - `profiles`: 三套模板参数

## 2. 一键切换脚本

脚本路径：`scripts/switch_vol_profile.py`

常用命令：

```bash
# 查看当前状态（配置值 + 运行时实际生效值）
python scripts/switch_vol_profile.py --status

# 切到 fusion（稳态）
python scripts/switch_vol_profile.py --profile fusion_safe

# 切到 hybrid（平衡）
python scripts/switch_vol_profile.py --profile hybrid_balance

# 切到 garch（激进）
python scripts/switch_vol_profile.py --profile garch_aggressive

# 打开紧急回滚（强制使用 fusion_safe）
python scripts/switch_vol_profile.py --rollback on

# 关闭紧急回滚（恢复按 active_profile 生效）
python scripts/switch_vol_profile.py --rollback off
```

## 3. 推荐切换顺序（今晚 A/B）

1. `fusion_safe`（先稳住）  
2. `hybrid_balance`（看提升与稳定性平衡）  
3. `garch_aggressive`（小流量试验）  

建议每次切换后至少观察 15-30 分钟（或一段完整盘中样本），再进入下一档。

## 4. 紧急回滚策略

当出现以下情况时建议立即回滚：

- 区间宽度明显异常（持续过宽或过窄）
- 命中率短时快速下滑
- 数据源波动导致预测抖动加剧

操作：

```bash
python scripts/switch_vol_profile.py --rollback on
```

该开关会强制运行时使用 `fusion_safe`，不依赖当前 `active_profile`。

## 5. 生效验证

### 5.1 配置与运行时参数验证

```bash
python scripts/switch_vol_profile.py --status
```

关注输出：

- `active_profile`
- `emergency_rollback_to_fusion`
- `applied_profile`
- `primary_method`
- `garch_blend_weight`

### 5.2 预测记录验证

```bash
python - <<'PY'
import json
from pathlib import Path
f=Path('data/prediction_records/predictions_20260403.json')
d=json.loads(f.read_text())
r=[x for x in d if x.get('symbol')=='510300'][-1]['prediction']
print('method=',r.get('method'))
print('garch_shadow=',r.get('garch_shadow'))
print('volume_factor=',r.get('volume_factor'))
print('ab_profile=',r.get('ab_profile'))
print('ab_rollback_active=',r.get('ab_rollback_active'))
PY
```

## 6. 注意事项

- 切换脚本只改 `ab_test` 两个开关，不会改其它业务参数。
- 运行时是否实际使用模板，由代码中的 profile 合并逻辑决定（已接入 `src/volatility_range.py`）。
- 若切换后未见变化，先执行 `--status` 再检查是否命中目标运行链路（on-demand / scheduled）。
