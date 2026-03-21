import json
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
TOOL_RUNNER = BASE_DIR / "tool_runner.py"

# 显式打印当前数据/缓存根目录，便于确认是否已切到 /home/xie/data
def print_cache_root():
    try:
        # 直接从 src.config_loader 读取 data_storage 配置
        sys.path.insert(0, str(BASE_DIR.parent))  # 确保可以导入 src
        from src.config_loader import load_system_config, get_data_storage_config  # type: ignore

        cfg = load_system_config(use_cache=True)
        storage = get_data_storage_config(cfg)
        data_dir = storage.get("data_dir")
        print(f"当前数据根目录(data_dir): {data_dir}")
    except Exception as e:
        print(f"无法检测数据根目录(data_dir): {e}")


def run_tool(name: str, params: dict):
    cmd = ["python3", str(TOOL_RUNNER), name, json.dumps(params, ensure_ascii=False)]
    print(f"\n=== {name} ===")
    print("命令:", " ".join(cmd))

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = proc.stdout.strip()
    print("原始输出(末尾几行):")
    for line in out.splitlines()[-10:]:
        print("  ", line)

    # 尝试从输出中解析最后一行 JSON
    result = None
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                result = json.loads(line)
                break
            except Exception:
                continue

    if result is None:
        print("解析结果: 无法从输出中解析 JSON")
        return

    success = result.get("success")
    source = result.get("source")
    data = result.get("data") or {}
    # 优先从常见字段取 count；如果没有，再从 klines / df 长度推断
    count = (
        data.get("count")
        or data.get("returned_count")
        or data.get("total_count")
    )
    if count is None and isinstance(data, dict):
        if "klines" in data and isinstance(data["klines"], list):
            count = len(data["klines"])
        elif "df" in data and isinstance(data["df"], list):
            count = len(data["df"])
    message = result.get("message")

    print("解析结果:")
    print("  success:", success)
    print("  source :", source)
    print("  count  :", count)
    print("  message:", message)


def main():
    if not TOOL_RUNNER.exists():
        print(f"找不到 tool_runner.py: {TOOL_RUNNER}", file=sys.stderr)
        sys.exit(1)

    # 先打印当前缓存/数据根目录，确认是否已使用 /home/xie/data
    print_cache_root()

    tests = [
        (
            "tool_fetch_index_minute",
            {
                "index_code": "000300",
                "period": "5",
                "lookback_days": 2,
                "mode": "test",
            },
        ),
        (
            "tool_fetch_etf_minute",
            {
                "etf_code": "510300",
                "period": "5",
                "lookback_days": 2,
                "mode": "test",
            },
        ),
        (
            "tool_read_index_minute",
            {
                "symbol": "000300",
                "period": "5",
                "date": None,
            },
        ),
        (
            "tool_read_etf_minute",
            {
                "symbol": "510300",
                "period": "5",
                "start_date": None,
                "end_date": None,
            },
        ),
        (
            "tool_fetch_index_historical",
            {
                "index_code": "000300",
                "period": "daily",
                "start_date": "20260201",
                "end_date": "20260226",
                "mode": "test",
            },
        ),
        (
            "tool_fetch_etf_historical",
            {
                "etf_code": "510300",
                "period": "daily",
                "start_date": "20260201",
                "end_date": "20260226",
                "mode": "test",
            },
        ),
        (
            "tool_fetch_option_minute",
            {
                "contract_code": "10010914",
                "date": None,
                "mode": "test",
            },
        ),
        (
            "tool_fetch_option_greeks",
            {
                "contract_code": "10010914",
                "date": None,
                "mode": "test",
            },
        ),
        (
            "tool_fetch_a50_data",
            {
                "symbol": "A50期指",
                "data_type": "both",
                "use_cache": True,
            },
        ),
    ]

    for name, params in tests:
        try:
            run_tool(name, params)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"\n*** 运行 {name} 出错: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()

