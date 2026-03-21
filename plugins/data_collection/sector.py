#!/usr/bin/env python3
"""
板块轮动数据采集模块
数据源：东方财富行业板块接口
"""

import requests
import json
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


def tool_fetch_sector_data(sector_type: str = "industry", period: str = "today") -> Dict:
    """
    获取板块轮动数据
    
    Args:
        sector_type: "industry"（行业板块）或 "concept"（概念板块）
        period: "today"（今日）/ "week"（本周）/ "month"（本月）
    
    Returns:
        包含板块涨跌幅数据的字典
    """
    # 1) 优先使用东方财富 JSONP 接口
    try:
        df = _fetch_sector_data_from_eastmoney(sector_type=sector_type, period=period)
        if df is not None and not df.empty:
            return _build_sector_response_from_df(df, sector_type)
        logger.warning("东方财富板块接口返回空 DataFrame，将尝试 AkShare 备用源")
    except Exception as e:  # noqa: BLE001
        logger.error(f"获取板块数据失败（东方财富接口）: {e}")

    # 2) 备用：AkShare 行业板块接口（无 net_inflow 也可用作热度评分基础）
    try:
        df = _fetch_sector_data_from_akshare(sector_type=sector_type)
        if df is not None and not df.empty:
            return _build_sector_response_from_df(df, sector_type)
        return {
            "status": "error",
            "error": "东方财富与 AkShare 板块接口均无有效数据",
            "sector_type": sector_type,
            "date": datetime.now().strftime("%Y-%m-%d"),
        }
    except Exception as e:  # noqa: BLE001
        logger.error(f"获取板块数据失败（AkShare 备用源）: {e}")
        return {
            "status": "error",
            "error": str(e),
            "sector_type": sector_type,
            "date": datetime.now().strftime("%Y-%m-%d"),
        }


def _fetch_sector_data_from_eastmoney(sector_type: str, period: str) -> Optional[pd.DataFrame]:
    """从东方财富 JSONP 接口获取板块数据，返回 DataFrame 或 None。"""
    # 根据类型选择不同的接口
    if sector_type == "industry":
        # 申万一级行业接口
        url = "http://data.eastmoney.com/DataCenter_V3/Industry/GetIndustry.ashx"
        params = {
            "code": "SW",
            "type": 1,
            "sty": "sw",
            "js": "var data={pages:(pc),data:[(x)]}",
        }
    else:  # concept
        # 概念板块接口
        url = "http://data.eastmoney.com/DataCenter_V3/Concept/GetConcept.ashx"
        params = {
            "code": "all",
            "type": "today",
            "sty": "f14",
            "js": "var data={pages:(pc),data:[(x)]}",
        }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "http://data.eastmoney.com/bkzj/",
    }

    response = requests.get(url, params=params, headers=headers, timeout=10)
    response.encoding = "utf-8"

    text = response.text.strip()
    if not text:
        raise ValueError("东方财富返回空响应")
    if text.startswith("var data="):
        text = text.replace("var data=", "", 1)
    # 兼容 UTF-8 BOM
    text = text.lstrip("\ufeff")

    data = json.loads(text)
    if not data or "data" not in data:
        raise ValueError("东方财富板块数据为空")

    records = []
    for item in data["data"]:
        if len(item) < 10:
            continue
        try:
            records.append(
                {
                    "sector_name": item[1] if len(item) > 1 else "",
                    "current_price": float(item[2]) if len(item) > 2 else 0,
                    "change_percent": float(item[3]) if len(item) > 3 else 0,
                    "volume": float(item[5]) if len(item) > 5 else 0,
                    "turnover": float(item[6]) if len(item) > 6 else 0,
                    "inflow": float(item[7]) if len(item) > 7 else 0,
                    "outflow": float(item[8]) if len(item) > 8 else 0,
                    "net_inflow": float(item[9]) if len(item) > 9 else 0,
                    "stock_count": int(item[10]) if len(item) > 10 else 0,
                    "rise_count": int(item[11]) if len(item) > 11 else 0,
                    "fall_count": int(item[12]) if len(item) > 12 else 0,
                }
            )
        except (ValueError, IndexError):
            continue

    if not records:
        raise ValueError("东方财富板块数据格式错误")

    df = pd.DataFrame(records)
    df = df[(df["sector_name"].astype(str).str.len() > 0) & (df["change_percent"].notna())]
    if df.empty:
        raise ValueError("东方财富无有效板块数据")
    return df


def _fetch_sector_data_from_akshare(sector_type: str) -> Optional[pd.DataFrame]:
    """
    使用 AkShare 行业/概念板块接口作为备用源。
    仅保证提供 sector_name + change_percent（net_inflow 若不可得则为 0）。
    """
    try:
        import akshare as ak  # type: ignore[import]
    except Exception as e:  # noqa: BLE001
        logger.error(f"AkShare 未安装或导入失败: {e}")
        return None

    if sector_type != "industry":
        # 目前仅对 industry 提供备用源；concept 可后续扩展
        return None

    try:
        df_raw = ak.stock_board_industry_name_em()
    except Exception as e:  # noqa: BLE001
        logger.error(f"AkShare 行业板块接口失败: {e}")
        return None

    if df_raw is None or df_raw.empty:
        return None

    df_raw = df_raw.copy()
    # 猜测/匹配列名：不同版本 AkShare 列名可能为「板块名称/名称/指数/涨跌幅/涨幅/涨跌幅%/主力净流入」等
    cols = {c: str(c) for c in df_raw.columns}
    name_col = None
    change_col = None
    net_col = None
    for c in df_raw.columns:
        s = str(c)
        if name_col is None and ("名称" in s or "板块" in s):
            name_col = c
        if change_col is None and ("涨跌幅" in s or "涨幅" in s):
            change_col = c
        if net_col is None and ("净流入" in s or "主力净流入" in s):
            net_col = c

    if name_col is None or change_col is None:
        logger.error("AkShare 行业板块数据缺少名称或涨跌幅列")
        return None

    df = pd.DataFrame(
        {
            "sector_name": df_raw[name_col],
            "change_percent": pd.to_numeric(df_raw[change_col], errors="coerce"),
            "net_inflow": pd.to_numeric(df_raw[net_col], errors="coerce") if net_col is not None else 0.0,
        }
    )
    df = df[(df["sector_name"].astype(str).str.len() > 0) & (df["change_percent"].notna())]
    if df.empty:
        return None
    return df


def _build_sector_response_from_df(df: pd.DataFrame, sector_type: str) -> Dict:
    """从标准化 DataFrame 构建 tool_fetch_sector_data 返回结构。"""
    df = df.copy()
    df = df.sort_values("change_percent", ascending=False)
    df["rank"] = range(1, len(df) + 1)

    top_gainers = df.head(5).to_dict("records")
    top_losers = df.tail(5).to_dict("records")
    net_inflow_series = df["net_inflow"] if "net_inflow" in df.columns else pd.Series([0] * len(df))
    top_inflow = df.assign(net_inflow=net_inflow_series).sort_values("net_inflow", ascending=False).head(5).to_dict("records")

    rotation_speed = _calculate_rotation_speed(df)
    etf_recommendations = _generate_etf_recommendations(df.head(10))
    signal = _generate_sector_signal(df, rotation_speed)

    return {
        "status": "success",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "sector_type": sector_type,
        "summary": {
            "total_sectors": len(df),
            "avg_change": round(df["change_percent"].mean(), 2),
            "max_gain": round(df["change_percent"].max(), 2),
            "max_loss": round(df["change_percent"].min(), 2),
            "total_inflow": round(float(net_inflow_series.sum()), 2),
            "rotation_speed": rotation_speed,
        },
        "leaders": {
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "top_inflow": top_inflow,
        },
        "etf_recommendations": etf_recommendations,
        "signal": signal,
        "all_data": df.head(20).to_dict("records"),
    }


def _calculate_rotation_speed(df: pd.DataFrame) -> str:
    """
    计算板块轮动速度
    
    Args:
        df: 板块数据DataFrame
    
    Returns:
        "slow" / "medium" / "fast"
    """
    # 计算涨幅方差
    variance = df["change_percent"].var()
    
    if variance > 15:
        return "fast"
    elif variance > 8:
        return "medium"
    else:
        return "slow"


def _generate_etf_recommendations(df: pd.DataFrame) -> List[Dict]:
    """
    根据板块表现生成ETF推荐
    
    Args:
        df: 前10个板块数据
    
    Returns:
        ETF推荐列表
    """
    # 板块到ETF映射
    sector_etf_map = {
        "计算机": "159999",  # 科技ETF
        "电子": "159999",  # 科技ETF
        "通信": "515880",  # 通信ETF
        "半导体": "512480",  # 半导体ETF
        "医药": "512010",  # 医药ETF
        "生物制品": "512010",  # 医药ETF
        "医疗服务": "512010",  # 医药ETF
        "食品饮料": "159928",  # 消费ETF
        "家用电器": "159928",  # 消费ETF
        "汽车": "512010",  # 医药ETF（暂时无汽车ETF，用医药代替）
        "电气设备": "515790",  # 光伏ETF
        "电力": "515790",  # 光伏ETF
        "银行": "512800",  # 银行ETF
        "非银金融": "512000",  # 券商ETF
        "房地产": "512200",  # 地产ETF
        "建筑材料": "512710",  # 建材ETF
        "国防军工": "512560",  # 军工ETF
        "有色金属": "512400",  # 有色ETF
        "化工": "515220",  # 化工ETF
        "机械设备": "159999",  # 科技ETF（暂时用）
    }
    
    recommendations = []
    seen_etfs = set()
    
    for _, row in df.iterrows():
        sector_name = row["sector_name"]
        
        # 查找对应的ETF
        for keyword, etf_code in sector_etf_map.items():
            if keyword in sector_name and etf_code not in seen_etfs:
                recommendations.append({
                    "sector_name": sector_name,
                    "etf_code": etf_code,
                    "sector_change": round(row["change_percent"], 2),
                    "sector_inflow": round(row["net_inflow"], 2),
                    "score": row["change_percent"] * 0.4 + row["net_inflow"] * 0.6
                })
                seen_etfs.add(etf_code)
                break
        
        if len(recommendations) >= 3:  # 最多推荐3个ETF
            break
    
    # 按分数排序
    recommendations.sort(key=lambda x: x["score"], reverse=True)
    
    return recommendations


def _generate_sector_signal(df: pd.DataFrame, rotation_speed: str) -> Dict:
    """
    生成板块信号
    
    Args:
        df: 板块数据
        rotation_speed: 轮动速度
    
    Returns:
        信号字典
    """
    # 计算市场强度
    avg_change = df["change_percent"].mean()
    positive_count = (df["change_percent"] > 0).sum()
    positive_ratio = positive_count / len(df) if len(df) > 0 else 0
    
    # 判断市场热度
    if avg_change > 1.5 and positive_ratio > 0.7:
        market_strength = "strong_bull"
        strength_desc = "强势牛市"
    elif avg_change > 0.5 and positive_ratio > 0.6:
        market_strength = "bull"
        strength_desc = "温和上涨"
    elif avg_change > -0.5 and positive_ratio > 0.4:
        market_strength = "neutral"
        strength_desc = "震荡市"
    elif avg_change > -2 and positive_ratio > 0.3:
        market_strength = "bear"
        strength_desc = "弱势下跌"
    else:
        market_strength = "strong_bear"
        strength_desc = "深度下跌"
    
    # 轮动速度判断
    if rotation_speed == "fast":
        rotation_desc = "快速轮动，适合短线"
        confidence = 0.7
    elif rotation_speed == "medium":
        rotation_desc = "中等轮动，适合波段"
        confidence = 0.8
    else:
        rotation_desc = "缓慢轮动，适合配置"
        confidence = 0.6
    
    # 风格判断
    top_sectors = df.head(3)
    tech_ratio = sum(1 for s in top_sectors["sector_name"] if "计算机" in s or "电子" in s or "通信" in s or "半导体" in s)
    
    if tech_ratio >= 2:
        style = "growth"
        style_desc = "成长风格"
        confidence = min(confidence + 0.1, 0.95)
    elif any("银行" in s or "保险" in s or "券商" in s for s in top_sectors["sector_name"]):
        style = "value"
        style_desc = "价值风格"
        confidence = confidence - 0.05
    else:
        style = "balanced"
        style_desc = "均衡配置"
    
    return {
        "market_strength": market_strength,
        "strength_description": strength_desc,
        "rotation_speed": rotation_speed,
        "rotation_description": rotation_desc,
        "style": style,
        "style_description": style_desc,
        "confidence": round(confidence, 2),
        "action": "积极布局" if market_strength in ["bull", "strong_bull"] else 
                 "谨慎操作" if market_strength == "neutral" else "观望等待"
    }


if __name__ == "__main__":
    # 测试
    result = tool_fetch_sector_data(sector_type="industry", period="today")
    print(json.dumps(result, indent=2, ensure_ascii=False))