#!/usr/bin/env python3
"""
逐一测试 tool_fetch_index_opening 依赖的原始接口
运行（在项目根目录）: python3 tests/manual/manual_index_opening_apis.py
"""
import sys
from datetime import datetime

def test_akshare_import():
    """检查 akshare 是否可用"""
    try:
        import akshare as ak
        print("✓ akshare 已安装:", ak.__version__ if hasattr(ak, '__version__') else "ok")
        return ak
    except ImportError as e:
        print("✗ akshare 未安装:", e)
        print("  安装: pip install akshare")
        return None

def test_stock_zh_index_spot_em(ak):
    """测试接口1: stock_zh_index_spot_em(symbol=...) 东方财富"""
    import time
    print("\n" + "=" * 60)
    print("接口1: ak.stock_zh_index_spot_em(symbol=...)")
    print("=" * 60)
    symbols_to_try = ["沪深重要指数", "上证系列指数", "深证系列指数", "中证系列指数"]
    for i, symbol in enumerate(symbols_to_try):
        if i > 0:
            time.sleep(1.5)  # 间隔降低被远端关闭概率
        try:
            df = ak.stock_zh_index_spot_em(symbol=symbol)
            if df is not None and not df.empty:
                print(f"  ✓ symbol='{symbol}' -> 行数={len(df)}, 列={list(df.columns)[:8]}...")
                for col in ['代码', 'code', 'symbol', '名称', 'name']:
                    if col in df.columns:
                        print(f"    示例: {col}={df[col].iloc[0] if len(df) else 'N/A'}")
                        break
            else:
                print(f"  ✗ symbol='{symbol}' -> 返回空")
        except Exception as e:
            print(f"  ✗ symbol='{symbol}' -> 异常: {e}")
    print()

def test_stock_zh_index_spot_sina(ak):
    """测试接口2: stock_zh_index_spot_sina() 新浪"""
    print("\n" + "=" * 60)
    print("接口2: ak.stock_zh_index_spot_sina()")
    print("=" * 60)
    try:
        df = ak.stock_zh_index_spot_sina()
        if df is not None and not df.empty:
            print(f"  ✓ 行数={len(df)}, 列={list(df.columns)}")
            # 找上证/沪深300 示例
            for col in ['代码', 'code', 'symbol']:
                if col in df.columns:
                    sample = df[df[col].astype(str).str.contains('000001|000300', na=False)].head(2)
                    if not sample.empty:
                        print(f"  示例(含000001/000300):")
                        print(sample[[c for c in ['代码','code','symbol','名称','name','今开','昨收','涨跌幅'] if c in sample.columns]].to_string())
                    break
        else:
            print("  ✗ 返回空")
    except Exception as e:
        print(f"  ✗ 异常: {e}")
    print()

def main():
    print("tool_fetch_index_opening 原始接口测试")
    print("时间:", datetime.now().isoformat())
    ak = test_akshare_import()
    if ak is None:
        sys.exit(1)
    test_stock_zh_index_spot_em(ak)
    test_stock_zh_index_spot_sina(ak)
    print("=" * 60)
    print("小结:")
    print("  接口1 东财 stock_zh_index_spot_em: 若遇 RemoteDisconnected 多为网络/环境限制，可主用接口2。")
    print("  接口2 新浪 stock_zh_index_spot_sina: 返回列含 代码/名称/今开/昨收/涨跌幅，可直接用于开盘数据。")
    print("全部测试完成。")

if __name__ == "__main__":
    main()
