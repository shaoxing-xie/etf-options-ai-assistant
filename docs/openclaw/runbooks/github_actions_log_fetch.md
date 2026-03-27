# GitHub Actions 日志获取兜底 Runbook

适用场景：`gh run view --log` / `--log-failed` 为空输出，无法直接定位失败 step。

## 前置条件

- 已安装 `gh`
- 已设置 `GH_TOKEN`（推荐从 `~/.openclaw/.env` 注入）

```bash
export GH_TOKEN="$(grep '^GITHUB_PAT=' ~/.openclaw/.env | cut -d= -f2- | tail -n 1)"
```

## 标准流程

### 1) 获取失败 run id

```bash
gh run list --repo <owner>/<repo> --limit 5
```

### 2) 首选尝试（快速路径）

```bash
export GH_PAGER=cat
gh run view <run_id> --repo <owner>/<repo> --log-failed
```

若输出为空，继续兜底流程。

### 3) 兜底流程（推荐）

```bash
RUN_ID=<run_id>
OWNER_REPO=<owner>/<repo>

rm -rf /tmp/gh-logs-$RUN_ID
mkdir -p /tmp/gh-logs-$RUN_ID
cd /tmp/gh-logs-$RUN_ID

gh api -H "Accept: application/vnd.github+json" \
  /repos/$OWNER_REPO/actions/runs/$RUN_ID/logs \
  > run-$RUN_ID-logs.zip

ls -la run-$RUN_ID-logs.zip
unzip -o run-$RUN_ID-logs.zip >/dev/null
grep -RIn "failed\\|error\\|exit code 1\\|Release safety gate" .
```

## 常见问题

### A. `gh run download` 返回 `no valid artifacts found to download`

- 原因：`gh run download` 下载的是 artifacts，不是 run logs。
- 处理：改用本 runbook 的 `gh api .../actions/runs/<id>/logs`。

### B. zip 大小为 0

使用以下命令检查 API 响应头与鉴权：

```bash
gh api -i /repos/<owner>/<repo>/actions/runs/<run_id>/logs | head -n 40
gh auth status
```

### C. 本地缺少 `rg`

可用 `grep -RIn` 替代：

```bash
grep -RIn "Release safety gate" .
grep -RIn "exit code 1" .
```

## 证据回传格式（Builder）

执行结束后必须回传：

```text
[COMMAND]
...
[STDOUT]
...
[STDERR]
...
[RAW_OUTPUT]
...
```

无证据禁止结论；Reviewer 按 `NO_EVIDENCE` 或 `UNKNOWN_CAUSE` 失败码处理。

