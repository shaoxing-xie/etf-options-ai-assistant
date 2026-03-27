# CI 自动修复演练记录（3 次）

本文用于验收 `run-three-ci-drills` 任务：记录三次演练证据、失败码、风险判定与 Evolver 产出。

## Drill-1：失败取证与根因定位

- Run ID: `23581206381`
- URL: <https://github.com/shaoxing-xie/etf-options-ai-assistant/actions/runs/23581206381>
- 状态：`failure`
- 证据摘要（RAW）：
  - `Release safety gate failed. Errors:`
  - `scripts/test_mootdx_index_realtime.py:6: absolute path leak -> cd /home/xie/etf-options-ai-assistant`
  - `Process completed with exit code 1`
- 失败码：`LOG_FETCH_FAILED`（当 `gh run view --log-failed` 为空时触发兜底）-> 兜底成功后进入根因判定
- Reviewer 判定：
  - `TEAM_OK`
  - `ROOT_CAUSE=absolute path leak in scripts/test_mootdx_index_realtime.py`
  - `FIX=remove hardcoded /home/xie/... path`
  - `RISK=LOW`

### Evolver 产出（Drill-1）

- `ERROR_CLASS=PATH_LEAK`
- `AUTOFIX_ALLOWED=YES`
- `STANDARD_COMMANDS`：
  1. `gh run list --repo shaoxing-xie/etf-options-ai-assistant --limit 5`
  2. `gh api /repos/shaoxing-xie/etf-options-ai-assistant/actions/runs/<run_id>/logs > run-<run_id>-logs.zip`
  3. `python3 scripts/release_safety_gate.py`
- `CHECKLIST_UPDATE`：
  1. 先取 RAW 日志，禁止先下结论
  2. `--log-failed` 为空即切 `gh api .../logs`
  3. 修复后本地先跑 gate 再 push

## Drill-2：修复后验证成功

- Run ID: `23621527878`
- URL: <https://github.com/shaoxing-xie/etf-options-ai-assistant/actions/runs/23621527878>
- 状态：`success`
- 关键结果：`release-gate` 通过，说明 LOW 风险修复有效。
- Reviewer 判定：
  - `TEAM_OK`
  - `RISK=LOW`
  - 可继续沿该协议执行自动修复类任务

### Evolver 产出（Drill-2）

- `ERROR_CLASS=FIX_VERIFIED`
- `AUTOFIX_ALLOWED=YES`
- `CHECKLIST_UPDATE`：
  1. 成功 run 仍需保留 run id 与摘要证据
  2. 把“根因->修复->验证”三元组沉淀到 SOP

## Drill-3：基线对照（稳定成功样本）

- Run ID: `23569814908`
- URL: <https://github.com/shaoxing-xie/etf-options-ai-assistant/actions/runs/23569814908>
- 状态：`success`
- 目的：作为修复前后对照基线，验证 `release-gate` 在无绝对路径泄漏时稳定通过。

### Evolver 产出（Drill-3）

- `ERROR_CLASS=BASELINE_PASS`
- `AUTOFIX_ALLOWED=YES`
- `CHECKLIST_UPDATE`：
  1. 对照成功样本可以缩短排障时间
  2. 对同类 gate 错误优先复用已验证修复路径

## 全局验收结论

- 三次演练均有 run 证据（失败 1 次 + 成功 2 次）。
- 已验证日志兜底路径（`gh run view --log*` 为空时改用 `gh api .../logs`）。
- 已形成标准失败码、证据块协议与 Evolver 复盘 checklist。
- 满足“全阶段强制门禁”的基础条件，可进入阶段 2（Cron/任务异常诊断 + safe-autofix）。

