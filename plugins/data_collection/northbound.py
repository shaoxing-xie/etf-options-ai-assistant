#!/usr/bin/env python3
"""
北向资金数据采集模块
数据源：东方财富沪深港通接口
"""

import requests
import json
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


def tool_fetch_northbound_flow(date: str = None, lookback_days: int = 1) -> Dict:
    """
    获取北向资金流向数据
    
    Args:
        date: 指定日期（YYYY-MM-DD），默认今天
        lookback_days: 回溯天数，用于获取历史数据
    
    Returns:
        包含北向资金流向数据的字典
    """
    try:
        # 默认今天
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        
        # 东方财富北向资金接口
        url = "http://data.eastmoney.com/DataCenter_V3/Trade2014/HsgtFlow.ashx"
        
        params = {
            "mr": "0",
            "t": "slhfa",
            "cb": "",
            "js": "var t={pages:(pc),data:[(x)]}",
            "dpt": "zjtz",
            "style": "all",
            "sc": "rand",
            "st": "desc",
            "rt": ""
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "http://data.eastmoney.com/hsgt/"
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.encoding = "utf-8"
        
        # 解析JSONP响应
        text = response.text
        if text.startswith("var t="):
            text = text.replace("var t=", "")
        
        data = json.loads(text)
        
        if not data or "data" not in data:
            return {
                "status": "error",
                "error": "北向资金数据为空",
                "date": date
            }
        
        # 解析数据
        records = []
        for item in data["data"]:
            record = {
                "date": item[0],  # 日期
                "sh_buy": float(item[1]) if item[1] else 0,  # 沪股通买入（亿）
                "sh_sell": float(item[2]) if item[2] else 0,  # 沪股通卖出（亿）
                "sh_net": float(item[3]) if item[3] else 0,  # 沪股通净流入（亿）
                "sz_buy": float(item[4]) if item[4] else 0,  # 深股通买入（亿）
                "sz_sell": float(item[5]) if item[5] else 0,  # 深股通卖出（亿）
                "sz_net": float(item[6]) if item[6] else 0,  # 深股通净流入（亿）
                "total_net": float(item[7]) if item[7] else 0,  # 总净流入（亿）
            }
            records.append(record)
        
        # 转换为DataFrame
        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date", ascending=False)
        
        # 截取指定天数
        df = df.head(lookback_days)
        
        # 计算统计信息
        latest = df.iloc[0].to_dict()
        latest["date"] = latest["date"].strftime("%Y-%m-%d")
        
        # 历史对比
        if len(df) >= 5:
            avg_5d = df.head(5)["total_net"].mean()
            avg_20d = df.head(20)["total_net"].mean() if len(df) >= 20 else None
        else:
            avg_5d = None
            avg_20d = None
        
        # 连续流入/流出
        consecutive_days = 0
        for _, row in df.iterrows():
            if (row["total_net"] > 0 and latest["total_net"] > 0) or \
               (row["total_net"] < 0 and latest["total_net"] < 0):
                consecutive_days += 1
            else:
                break
        
        # 生成信号
        signal = _generate_signal(latest, avg_5d, consecutive_days)
        
        return {
            "status": "success",
            "date": latest["date"],
            "data": {
                "sh_net": latest["sh_net"],
                "sz_net": latest["sz_net"],
                "total_net": latest["total_net"],
                "sh_buy": latest["sh_buy"],
                "sh_sell": latest["sh_sell"],
                "sz_buy": latest["sz_buy"],
                "sz_sell": latest["sz_sell"]
            },
            "statistics": {
                "avg_5d": round(avg_5d, 2) if avg_5d else None,
                "avg_20d": round(avg_20d, 2) if avg_20d else None,
                "consecutive_days": consecutive_days,
                "trend": "流入" if latest["total_net"] > 0 else "流出"
            },
            "signal": signal,
            "history": df.head(lookback_days).to_dict("records")
        }
        
    except Exception as e:
        logger.error(f"获取北向资金数据失败: {e}")
        return {
            "status": "error",
            "error": str(e),
            "date": date if date else datetime.now().strftime("%Y-%m-%d")
        }


def _generate_signal(latest: Dict, avg_5d: Optional[float], consecutive_days: int) -> Dict:
    """
    生成北向资金信号
    
    Args:
        latest: 最新数据
        avg_5d: 5日均值
        consecutive_days: 连续流入/流出天数
    
    Returns:
        信号字典
    """
    total_net = latest["total_net"]
    
    # 信号强度判断
    if total_net > 100:
        strength = "strong_buy"
        confidence = 0.85
        description = "大幅流入（>100亿），强烈看多"
    elif total_net > 50:
        strength = "buy"
        confidence = 0.75
        description = "显著流入（>50亿），看多"
    elif total_net > 20:
        strength = "light_buy"
        confidence = 0.65
        description = "小幅流入（>20亿），偏多"
    elif total_net > 0:
        strength = "neutral_positive"
        confidence = 0.55
        description = "微幅流入，中性偏多"
    elif total_net > -20:
        strength = "neutral_negative"
        confidence = 0.55
        description = "微幅流出，中性偏空"
    elif total_net > -50:
        strength = "sell"
        confidence = 0.65
        description = "显著流出（>50亿），风险"
    else:
        strength = "strong_sell"
        confidence = 0.75
        description = "大幅流出（>50亿），强烈风险信号"
    
    # 趋势确认
    if consecutive_days >= 3:
        if total_net > 0:
            description += f"，连续{consecutive_days}日流入，趋势确认"
            confidence = min(confidence + 0.1, 0.95)
        else:
            description += f"，连续{consecutive_days}日流出，风险确认"
            confidence = min(confidence + 0.1, 0.95)
    
    # 对比5日均值
    if avg_5d and abs(total_net) > abs(avg_5d) * 1.5:
        description += f"，超预期（5日均值{avg_5d:.2f}亿）"
        confidence = min(confidence + 0.05, 0.95)
    
    return {
        "strength": strength,
        "confidence": round(confidence, 2),
        "description": description,
        "action": "关注" if total_net > 20 else "观望" if total_net > -20 else "风险"
    }


if __name__ == "__main__":
    # 测试
    result = tool_fetch_northbound_flow(lookback_days=5)
    print(json.dumps(result, indent=2, ensure_ascii=False))
