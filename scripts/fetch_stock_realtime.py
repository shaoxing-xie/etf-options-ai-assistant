#!/usr/bin/env python3
"""
实时行情获取模块（供 alert_engine 使用）
封装 AkShare 获取 A 股实时数据

用法示例（在项目根目录执行）：
  # 作为库被 alert_engine 调用（最常见）
  python3 scripts/alert_poll.py

  # 作为 CLI 直接拉取（若脚本支持命令行参数；见文件末尾 Usage）
  python3 scripts/fetch_stock_realtime.py 510300 600519
"""

import sys
import json


def fetch_batch(codes: list[str]) -> dict:
    """
    批量获取 A 股实时行情。
    返回格式: {code: {current: float, change_pct: float, high, low, volume, prev_close}}
    """
    result = {}
    
    try:
        import akshare as ak
        
        # 构造股票代码列表
        code_list = ",".join(codes)
        
        # 使用 akshare 获取实时行情
        try:
            df = ak.stock_zh_a_spot_em()
            
            for code in codes:
                # 处理代码格式：600900 → 600900.SH
                row = df[df['代码'] == code]
                if not row.empty:
                    row = row.iloc[0]
                    result[code] = {
                        "current": float(row.get('最新价', 0) or 0),
                        "change_pct": float(row.get('涨跌幅', 0) or 0),
                        "high": float(row.get('最高', 0) or 0),
                        "low": float(row.get('最低', 0) or 0),
                        "volume": float(row.get('成交量', 0) or 0),
                        "prev_close": float(row.get('昨收', 0) or 0),
                        "open": float(row.get('开盘', 0) or 0),
                        "name": str(row.get('名称', '')),
                    }
                else:
                    print(f"[WARN] Code {code} not found in spot data")
                    
        except Exception as e:
            print(f"[ERROR] akshare stock_zh_a_spot_em failed: {e}")
            # 回退：逐个获取
            for code in codes:
                try:
                    df_single = ak.stock_zh_a_hist(
                        symbol=code,
                        period="daily",
                        start_date="20260312",
                        end_date="20260313",
                        adjust="qfq"
                    )
                    if not df_single.empty:
                        last = df_single.iloc[-1]
                        prev = df_single.iloc[-2] if len(df_single) > 1 else last
                        current = float(last.get('收盘', 0))
                        prev_close = float(prev.get('收盘', current))
                        change_pct = ((current - prev_close) / prev_close * 100) if prev_close else 0
                        result[code] = {
                            "current": current,
                            "change_pct": round(change_pct, 2),
                            "high": float(last.get('最高', 0)),
                            "low": float(last.get('最低', 0)),
                            "volume": float(last.get('成交量', 0)),
                            "prev_close": prev_close,
                            "open": float(last.get('开盘', 0)),
                        }
                except Exception as e2:
                    print(f"[ERROR] Failed to fetch {code}: {e2}")
                    
    except ImportError:
        print("[WARN] akshare not available, trying mootdx")
        # 回退到 mootdx
        result = fetch_batch_mootdx(codes)
    
    return result


def fetch_batch_mootdx(codes: list[str]) -> dict:
    """
    使用 mootdx 获取实时行情（备用方案）
    """
    result = {}
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market='std')
        
        for code in codes:
            try:
                # A股代码处理
                if code.startswith('6'):
                    full_code = f"sh{code}"
                elif code.startswith(('0', '3')):
                    full_code = f"sz{code}"
                else:
                    full_code = code
                    
                df = client.bars(symbol=code, frequency='1d', offset=1)
                if df is not None and not df.empty:
                    row = df.iloc[-1]
                    prev_df = client.bars(symbol=code, frequency='1d', offset=2)
                    prev_close = float(prev_df.iloc[-2]['close']) if prev_df is not None and len(prev_df) > 1 else float(row['close'])
                    current = float(row['close'])
                    change_pct = ((current - prev_close) / prev_close * 100) if prev_close else 0
                    
                    result[code] = {
                        "current": current,
                        "change_pct": round(change_pct, 2),
                        "high": float(row.get('high', 0)),
                        "low": float(row.get('low', 0)),
                        "volume": float(row.get('volume', 0)),
                        "prev_close": prev_close,
                        "open": float(row.get('open', 0)),
                    }
            except Exception as e:
                print(f"[ERROR] mootdx fetch {code} failed: {e}")
    except ImportError:
        print("[ERROR] Neither akshare nor mootdx available")
    
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: fetch_stock_realtime.py <code1> [code2] ...")
        sys.exit(1)
    
    codes = sys.argv[1:]
    data = fetch_batch(codes)
    print(json.dumps(data, ensure_ascii=False, indent=2))
