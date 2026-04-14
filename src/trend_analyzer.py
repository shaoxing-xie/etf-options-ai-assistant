"""
趋势分析模块
实现盘后分析和开盘前分析
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import pytz
import json
from pathlib import Path

from src.logger_config import get_module_logger, log_error_with_context
from src.data_collector import (
    fetch_index_daily_em, fetch_global_index_hist_em,
    fetch_index_opening_history,
    fetch_a50_daily_sina_hist
    # 注意：fetch_a50_daily_sina 已移除，新浪财经CN_MarketData.getKLineData接口不支持A50期货数据（返回null）
    # 使用 fetch_a50_daily_sina_hist（通过AKShare的futures_foreign_hist接口获取新浪财经数据）
)
from src.indicator_calculator import calculate_macd, calculate_ma

logger = get_module_logger(__name__)


def _last_bar_yyyymmdd_from_index_df(df: Optional[pd.DataFrame]) -> Optional[str]:
    """取指数日线 DataFrame 中最后一根 K 线的日期（YYYYMMDD），按日期列排序后取末行，避免缓存乱序误读。"""
    if df is None or df.empty or "日期" not in df.columns:
        return None
    try:
        dfc = df.copy()
        dfc["日期"] = pd.to_datetime(dfc["日期"], errors="coerce")
        dfc = dfc.dropna(subset=["日期"]).sort_values("日期")
        if dfc.empty:
            return None
        last = dfc["日期"].iloc[-1]
        return pd.Timestamp(last).strftime("%Y%m%d")
    except Exception:
        last_date = str(df["日期"].iloc[-1])
        if len(last_date) == 8 and last_date.isdigit():
            return last_date
        try:
            return pd.to_datetime(last_date).strftime("%Y%m%d")
        except Exception:
            return None


def _hxc_cache_path() -> Path:
    return Path("data/cache/global_index").joinpath("hxc_close_cache.json")


def _load_hxc_close_cache() -> Dict[str, float]:
    try:
        p = _hxc_cache_path()
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
        if not isinstance(data, dict):
            return {}
        out: Dict[str, float] = {}
        for k, v in data.items():
            try:
                out[str(k)] = float(v)
            except Exception:
                continue
        return out
    except Exception:
        return {}


def _save_hxc_close_cache(cache: Dict[str, float]) -> None:
    try:
        p = _hxc_cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def _extract_date_yyyymmdd_from_row(row: pd.Series) -> Optional[str]:
    """从一行数据中提取日期（YYYYMMDD），兼容多级列名。"""
    if row is None:
        return None
    date_val = None
    # 直接遍历，避免 Index membership 在某些类型上异常
    for k in row.index:
        if k == "日期":
            date_val = row.get(k)
            break
        if isinstance(k, tuple) and len(k) >= 1 and str(k[0]) == "日期":
            date_val = row.get(k)
            break
        if str(k).lower() in ("date", "datetime"):
            date_val = row.get(k)
            break
    if date_val is None and len(row.index) > 0:
        date_val = row.iloc[0]

    try:
        dt = pd.to_datetime(date_val, errors="coerce")
        if pd.notna(dt):
            if isinstance(dt, pd.Timestamp):
                return dt.strftime("%Y%m%d")
            return str(dt).replace("-", "").replace("/", "")[:8]
    except Exception:
        pass
    if isinstance(date_val, str) and date_val.strip():
        return date_val.replace("-", "").replace("/", "")[:8]
    return None


def _extract_close_from_row(row: pd.Series) -> Optional[float]:
    """从一行数据中提取收盘价，兼容多级列名。"""
    # 不使用 pd.notna 以避免某些对象类型触发异常被吞
    if row is None:
        return None
    # 兼容单层列
    if "收盘" in row.index:
        try:
            return float(row["收盘"])
        except Exception:
            pass
    # 兼容多级列：('收盘', '^HXC') 等
    for k in row.index:
        if k == "收盘":
            try:
                return float(row[k])
            except Exception:
                continue
        if isinstance(k, tuple) and len(k) >= 1 and str(k[0]) == "收盘":
            try:
                return float(row[k])
            except Exception:
                continue
    return None


def _extract_close_series(df: pd.DataFrame) -> Optional[pd.Series]:
    """从DataFrame中提取收盘列（Series），兼容多级列名。"""
    if df is None or df.empty:
        return None
    if "收盘" in df.columns:
        return df["收盘"]
    for c in df.columns:
        if isinstance(c, tuple) and len(c) >= 1 and str(c[0]) == "收盘":
            return df[c]
    return None

def _fetch_market_breadth_sina(
    max_retries: int = 3,
    cache_dir: str = "data/cache",
    cache_ttl_seconds: int = 6 * 60 * 60,
    force_refresh: bool = False,
) -> dict:
    """
    获取全市场涨跌家数（Sina: Market_Center.getHQNodeData）

    背景：
    - 直接调用 akshare.stock_zh_a_spot() 会遍历全量分页，且不带请求头，容易被新浪返回 HTML 拦截页，
      触发 demjson.JSONDecodeError: Can not decode value starting with character '<'
    - 这里实现一个更稳的“只统计涨跌家数”的版本：带 Referer/UA，逐页统计，不构建大 DataFrame。

    额外增强：
    - 加“每日缓存”，避免盘后分析/工作流重复运行导致高频请求触发风控。
    """
    try:
        import json
        import os
        import re
        import time
        from datetime import datetime
        import requests
        from akshare.stock.cons import (
            zh_sina_a_stock_url,
            zh_sina_a_stock_payload,
            zh_sina_a_stock_count_url,
        )
        from akshare.utils import demjson

        headers = {
            "Referer": "https://vip.stock.finance.sina.com.cn/mkt/#hs_a",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }

        def _safe_float(v: Any) -> Optional[float]:
            """安全转换为 float；失败返回 None（避免 Bandit 的 try/except + continue）。"""
            try:
                return float(v)
            except Exception as e:
                logger.debug(f"安全转 float 失败: v={v}, 错误: {e}", exc_info=True)
                return None

        # ========== 0) 读取缓存（同一天内复用） ==========
        today = datetime.now().strftime("%Y%m%d")
        cache_path = os.path.join(cache_dir, f"market_breadth_{today}.json")
        if not force_refresh:
            try:
                if os.path.exists(cache_path):
                    st = os.stat(cache_path)
                    if (time.time() - st.st_mtime) <= cache_ttl_seconds:
                        with open(cache_path, "r", encoding="utf-8") as f:
                            cached = json.load(f) or {}
                        if isinstance(cached, dict) and cached.get("success"):
                            cached["source"] = str(cached.get("source") or "sina_market_center") + "+cache"
                            return cached
            except Exception as e:
                # 缓存读取失败不影响主流程
                logger.debug(f"缓存读取失败，忽略: {e}", exc_info=True)

        session = requests.Session()
        session.headers.update(headers)

        def _is_html(text: str) -> bool:
            t = (text or "").lstrip()
            return t.startswith("<!DOCTYPE html") or t.startswith("<html") or t.startswith("<")

        # 1) 获取总页数（每页 80）
        page_count = None
        last_err = None
        for attempt in range(max_retries):
            try:
                res = session.get(zh_sina_a_stock_count_url, timeout=10)
                txt = res.text or ""
                if _is_html(txt):
                    raise ValueError("Sina 返回 HTML（疑似拦截页）")
                nums = re.findall(re.compile(r"\d+"), txt)
                if not nums:
                    raise ValueError(f"无法解析总数: {txt[:120]}")
                total = int(nums[0])
                page_count = total // 80 + (1 if total % 80 else 0)
                break
            except Exception as e:
                last_err = e
                if attempt < max_retries - 1:
                    time.sleep(1.0)
        if not page_count:
            raise RuntimeError(f"获取新浪A股分页数失败: {last_err}")

        # 2) 逐页统计涨跌家数
        payload = zh_sina_a_stock_payload.copy()
        rising = 0
        falling = 0
        total_rows = 0
        for page in range(1, page_count + 1):
            payload.update({"page": str(page)})
            # 轻微节流，降低触发风控概率
            if page > 1:
                time.sleep(0.05)
            r = session.get(zh_sina_a_stock_url, params=payload, timeout=10)
            txt = r.text or ""
            if _is_html(txt):
                raise ValueError("Sina 返回 HTML（疑似拦截页）")
            data = demjson.decode(txt)
            if not isinstance(data, list):
                raise ValueError(f"Sina 返回非列表: {type(data)}")
            for row in data:
                if not isinstance(row, dict):
                    continue
                # akshare 字段：changepercent
                cp = row.get("changepercent")
                cpv = _safe_float(cp)
                if cpv is None:
                    continue
                if cpv > 0:
                    rising += 1
                elif cpv < 0:
                    falling += 1
                total_rows += 1

        ratio = (rising / total_rows) if total_rows else None
        result = {
            "success": bool(total_rows),
            "source": "sina_market_center",
            "rising_count": rising,
            "falling_count": falling,
            "total_count": total_rows,
            "rising_ratio": ratio,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        # ========== 3) 写入缓存 ==========
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"写入缓存失败，忽略: {e}", exc_info=True)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}



def judge_overall_trend(
    shanghai_trend: str,
    hs300_trend: str,
    rising_ratio: float
) -> tuple[str, float]:
    """
    综合判断整体趋势（结合上证指数和沪深300）
    
    Args:
        shanghai_trend: 上证指数趋势（"强势"、"弱势"、"震荡"）
        hs300_trend: 沪深300趋势
        rising_ratio: 上涨股票比例
    
    Returns:
        tuple: (趋势方向, 趋势强度 0-1)
    """
    try:
        # 权重：上证指数40%，沪深30040%，市场情绪20%
        trend_scores = {
            "强势": 1.0,
            "震荡": 0.5,
            "弱势": 0.0
        }
        
        shanghai_score = trend_scores.get(shanghai_trend, 0.5)
        hs300_score = trend_scores.get(hs300_trend, 0.5)
        market_sentiment = rising_ratio  # 上涨比例作为市场情绪
        
        # 综合得分
        overall_score = shanghai_score * 0.4 + hs300_score * 0.4 + market_sentiment * 0.2
        
        # 判断趋势方向
        if overall_score >= 0.7:
            trend = "强势"
            strength = overall_score
        elif overall_score <= 0.3:
            trend = "弱势"
            strength = 1.0 - overall_score
        else:
            trend = "震荡"
            strength = abs(overall_score - 0.5) * 2  # 震荡时强度较低
        
        logger.info(f"整体趋势判断: {trend}, 强度: {strength:.2f}, 得分: {overall_score:.2f}")
        return trend, strength
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'judge_overall_trend', 'shanghai_trend': shanghai_trend, 'hs300_trend': hs300_trend},
            "判断整体趋势失败"
        )
        return "震荡", 0.5


def analyze_index_trend(
    daily_df: pd.DataFrame,
    index_name: str = "000300",
    use_arima: bool = True
) -> tuple[str, float]:
    """
    分析指数趋势（日线级别）
    支持ARIMA预测（GK优化）和技术指标（MACD/RSI）结合
    
    Args:
        daily_df: 日线数据DataFrame
        index_name: 指数名称
        use_arima: 是否使用ARIMA预测（默认True，GK优化）
    
    Returns:
        tuple: (趋势方向, 趋势强度)
    """
    try:
        if daily_df is None or daily_df.empty:
            logger.warning(f"指数数据为空: {index_name}")
            return "震荡", 0.5
        
        # 计算技术指标（MACD/RSI/MA）
        macd_result = calculate_macd(daily_df, close_col='收盘')
        ma20 = calculate_ma(daily_df, period=20, close_col='收盘')
        ma60 = calculate_ma(daily_df, period=60, close_col='收盘')
        
        if macd_result is None or ma20 is None or ma60 is None:
            logger.warning(f"技术指标计算失败: {index_name}")
            return "震荡", 0.5
        
        # 获取最新值
        latest_close = daily_df['收盘'].iloc[-1]
        latest_ma20 = ma20.iloc[-1]
        latest_ma60 = ma60.iloc[-1]
        latest_macd = macd_result['macd'].iloc[-1]
        latest_signal = macd_result['signal'].iloc[-1]
        latest_histogram = macd_result['histogram'].iloc[-1]
        
        # 判断趋势（技术指标方法）
        trend_score = 0.0
        
        # MA判断（40%权重）
        if latest_close > latest_ma20 > latest_ma60:
            trend_score += 0.4  # 多头排列
        elif latest_close < latest_ma20 < latest_ma60:
            trend_score += 0.0  # 空头排列
        else:
            trend_score += 0.2  # 震荡
        
        # MACD判断（40%权重）
        if latest_macd > latest_signal and latest_histogram > 0:
            trend_score += 0.4  # MACD金叉且柱状图为正
        elif latest_macd < latest_signal and latest_histogram < 0:
            trend_score += 0.0  # MACD死叉且柱状图为负
        else:
            trend_score += 0.2  # 震荡
        
        # 价格位置判断（20%权重）
        if latest_close > latest_ma20:
            trend_score += 0.2
        else:
            trend_score += 0.0
        
        # 转换为趋势方向（技术指标）
        if trend_score >= 0.7:
            technical_trend = "强势"
            technical_strength = trend_score
        elif trend_score <= 0.3:
            technical_trend = "弱势"
            technical_strength = 1.0 - trend_score
        else:
            technical_trend = "震荡"
            technical_strength = abs(trend_score - 0.5) * 2
        
        # GK优化：如果启用ARIMA，结合ARIMA预测
        if use_arima:
            try:
                from src.trend_analyzer_arima import predict_index_trend_arima, combine_trend_analysis
                
                # ARIMA预测（3天，使用优化后的参数）
                # 自动选择阶数、扩展数据窗口到200天、改进置信度、动态阈值
                arima_result = predict_index_trend_arima(
                    daily_df, 
                    forecast_days=3,
                    auto_select_order=True,  # 自动选择最优阶数
                    data_window_days=200,   # 扩展数据窗口到200天
                    use_volume=False        # 暂时不使用成交量（如果需要可以传递volume_df）
                )
                
                # 结合ARIMA和技术指标
                combined_result = combine_trend_analysis(arima_result, (technical_trend, technical_strength))
                
                final_trend = combined_result['final_trend']
                final_strength = combined_result['final_strength']
                
                logger.info(f"{index_name}趋势分析 (ARIMA+技术指标): {final_trend}, 强度: {final_strength:.2f}, "
                           f"ARIMA={arima_result.get('direction', 'N/A')}(阶数={arima_result.get('arima_order', 'N/A')}, "
                           f"置信度={arima_result.get('confidence', 0):.2f}), 技术指标={technical_trend}")
                
                return final_trend, final_strength
                
            except ImportError:
                logger.debug("ARIMA模块不可用，仅使用技术指标")
            except Exception as e:
                logger.warning(f"ARIMA预测失败: {e}，仅使用技术指标")
        
        # 如果ARIMA不可用或失败，仅使用技术指标
        logger.info(f"{index_name}趋势分析 (技术指标): {technical_trend}, 强度: {technical_strength:.2f}, 得分: {trend_score:.2f}")
        return technical_trend, technical_strength
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'analyze_index_trend', 'index_name': index_name},
            "分析指数趋势失败"
        )
        return "震荡", 0.5


def analyze_daily_market_after_close(config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    每天盘后15:30执行
    分析当天市场情况，预测下一交易日整体趋势
    结合上证指数(000001)和沪深300(000300)的趋势
    
    Args:
        config: 系统配置
    
    Returns:
        dict: 分析报告
    """
    try:
        logger.info("开始盘后分析...")

        tz_sh = pytz.timezone("Asia/Shanghai")
        now_sh = datetime.now(tz_sh)
        today = now_sh.strftime("%Y%m%d")
        try:
            from src.system_status import get_expected_latest_a_share_daily_bar_date

            expected_bar_date = get_expected_latest_a_share_daily_bar_date(now_sh, config)
        except Exception:
            expected_bar_date = today
        # 回看120个日历日，确保有足够的交易日数据（60个交易日 ≈ 90个日历日，增加缓冲确保有足够数据）
        # 考虑到节假日和周末，120个日历日通常能提供约80个交易日，足够计算MA60
        start_date = (now_sh - timedelta(days=120)).strftime("%Y%m%d")
        
        # ========== 数据获取与验证（支持缓存强制刷新） ==========
        max_attempts = 2  # 最多尝试2次
        shanghai_daily = None
        hs300_daily = None
        data_stale_warning = None  # 数据过期时的明确提示，将写入报告
        shanghai_last_date = None
        hs300_last_date = None
        
        for attempt in range(max_attempts):
            # 第一次尝试：正常获取（可能使用缓存）
            # 第二次尝试：如果数据日期不对，清除缓存后重新获取
            force_refresh = (attempt > 0)
            
            if force_refresh:
                logger.warning(f"数据日期验证失败，强制刷新缓存后重新获取（尝试 {attempt+1}/{max_attempts}）")
                # 清除今天的缓存
                try:
                    from src.data_cache import clear_index_daily_cache
                    clear_index_daily_cache("000001", today, config=config)
                    clear_index_daily_cache("000300", today, config=config)
                    logger.info("已清除今天的指数日线缓存")
                except Exception as e:
                    logger.warning(f"清除缓存失败: {e}")
            
            # 1/2. 并行获取上证与沪深300日线，避免串行耗时叠加导致上游工具超时
            per_fetch_timeout_seconds = 20
            if isinstance(config, dict):
                ta_cfg = config.get("trend_analysis_plugin", {}) or {}
                try:
                    per_fetch_timeout_seconds = int(
                        ta_cfg.get("index_fetch_timeout_seconds", per_fetch_timeout_seconds)
                    )
                except Exception:
                    pass

            executor = ThreadPoolExecutor(max_workers=2)
            future_sh = executor.submit(
                fetch_index_daily_em,
                symbol="000001",
                period="daily",
                start_date=start_date,
                end_date=today,
            )
            future_hs300 = executor.submit(
                fetch_index_daily_em,
                symbol="000300",
                period="daily",
                start_date=start_date,
                end_date=today,
            )
            try:
                try:
                    shanghai_daily = future_sh.result(timeout=max(5, per_fetch_timeout_seconds))
                except Exception as e:
                    logger.warning(f"获取上证指数日线超时/失败，后续使用降级口径: {e}")
                    shanghai_daily = None
                    future_sh.cancel()
                try:
                    hs300_daily = future_hs300.result(timeout=max(5, per_fetch_timeout_seconds))
                except Exception as e:
                    logger.warning(f"获取沪深300日线超时/失败，后续使用降级口径: {e}")
                    hs300_daily = None
                    future_hs300.cancel()
            finally:
                # 避免因单路阻塞导致退出阶段长时间等待，确保主流程按预算返回
                executor.shutdown(wait=False, cancel_futures=True)
            
            # 3. 验证数据日期是否与「最近一根完整日线」应对齐的交易日一致（盘前不应要求等于日历当日）
            data_date_valid = True
            
            if shanghai_daily is not None and not shanghai_daily.empty:
                if "日期" in shanghai_daily.columns:
                    shanghai_last_date = _last_bar_yyyymmdd_from_index_df(shanghai_daily)
                    if shanghai_last_date and shanghai_last_date != expected_bar_date:
                        logger.warning(
                            "上证指数数据日期与期望最近完整交易日不一致: "
                            f"期望={expected_bar_date}, 实际={shanghai_last_date}"
                        )
                        data_date_valid = False

            if hs300_daily is not None and not hs300_daily.empty:
                if "日期" in hs300_daily.columns:
                    hs300_last_date = _last_bar_yyyymmdd_from_index_df(hs300_daily)
                    if hs300_last_date and hs300_last_date != expected_bar_date:
                        logger.warning(
                            "沪深300数据日期与期望最近完整交易日不一致: "
                            f"期望={expected_bar_date}, 实际={hs300_last_date}"
                        )
                        data_date_valid = False
            
            # 如果数据日期验证通过，或已经是最后一次尝试，跳出循环
            if data_date_valid or attempt >= max_attempts - 1:
                if data_date_valid:
                    logger.info(
                        f"数据日期验证通过: 上证/沪深300 最新日线与期望一致({expected_bar_date})"
                    )
                else:
                    # 明确提示：数据日期不匹配（交易日与非交易日口径区分）
                    actual_dates = []
                    if shanghai_last_date:
                        actual_dates.append(f"上证指数={shanghai_last_date}")
                    if hs300_last_date:
                        actual_dates.append(f"沪深300={hs300_last_date}")
                    actual_str = ", ".join(actual_dates) if actual_dates else "未知"
                    try:
                        from src.system_status import is_trading_day

                        today_dt = tz_sh.localize(datetime.strptime(today, "%Y%m%d"))
                        cal_today_is_trading = is_trading_day(today_dt, config)
                    except Exception:
                        cal_today_is_trading = True
                    if not cal_today_is_trading:
                        data_stale_warning = (
                            f"ℹ️ **数据日期说明**：日历日 {today} 为非 A 股交易日（周末或节假日），"
                            f"指数日线最新 bar 为上一交易日（{actual_str}）属**正常现象**；"
                            f"本报告基于最近可用交易日收市数据，非数据源故障。"
                        )
                    else:
                        data_stale_warning = (
                            f"⚠️ 数据日期不匹配：期望最近完整交易日({expected_bar_date})，实际最新数据({actual_str})。"
                            f"可能原因：数据源未更新、本地缓存异常或交易日盘后尚未落库。当前分析基于旧数据，结论可能不准确，请谨慎参考。"
                        )
                    logger.error("=" * 60)
                    logger.error("【盘后分析】数据日期验证失败")
                    logger.error(f"  期望最近完整交易日: {expected_bar_date}")
                    logger.error(f"  实际数据: 上证指数={shanghai_last_date or '无'}, 沪深300={hs300_last_date or '无'}")
                    logger.error(f"  已尝试 {max_attempts} 次刷新缓存，数据源仍未更新")
                    logger.error("  将使用当前数据继续分析，结论可能不准确，请谨慎参考")
                    logger.error("=" * 60)
                break
        # ========== 数据获取与验证结束 ==========
        
        # 3/4. 分析指数趋势
        # 根因修复：ARIMA在盘后路径耗时高（常超过工具超时），默认关闭以保证 cron 稳定返回。
        use_arima_after_close = False
        if isinstance(config, dict):
            ta_cfg = config.get("trend_analysis_plugin", {}) or {}
            use_arima_after_close = bool(ta_cfg.get("after_close_use_arima", False))
        shanghai_trend, shanghai_strength = analyze_index_trend(
            shanghai_daily, "000001", use_arima=use_arima_after_close
        )
        hs300_trend, hs300_strength = analyze_index_trend(
            hs300_daily, "000300", use_arima=use_arima_after_close
        )
        
        # 5. 计算市场情绪（上涨股票比例）
        # 尝试获取全市场数据，如果失败则使用指数涨跌作为参考
        rising_ratio = 0.5  # 默认值
        rising_count = None  # 初始为 None，表示数据不可用
        falling_count = None  # 初始为 None，表示数据不可用
        
        try:
            # 尝试获取A股整体数据（涨跌家数）
            # 说明：该步骤在部分网络环境会较慢；若超过预算则快速降级为指数推算，
            # 避免拖垮 tool_analyze_after_close 导致上游超时/Command failed。
            breadth_timeout_seconds = 8
            if isinstance(config, dict):
                ta_cfg = config.get("trend_analysis_plugin", {}) or {}
                try:
                    breadth_timeout_seconds = int(
                        ta_cfg.get("breadth_timeout_seconds", breadth_timeout_seconds)
                    )
                except Exception:
                    pass

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_fetch_market_breadth_sina, 3)
                breadth = future.result(timeout=max(2, breadth_timeout_seconds))
            if breadth.get("success"):
                rising_count = int(breadth.get("rising_count") or 0)
                falling_count = int(breadth.get("falling_count") or 0)
                total_count = int(breadth.get("total_count") or (rising_count + falling_count))
                if total_count > 0:
                    rising_ratio = float(breadth.get("rising_ratio") or (rising_count / total_count))
                logger.info(
                    f"市场情绪({breadth.get('source')}): 上涨{rising_count}家, 下跌{falling_count}家, 上涨比例{rising_ratio:.2%}"
                )
            else:
                err = breadth.get("error", "unknown")
                logger.warning(f"获取全市场涨跌家数失败（新浪 market_center）: {err}")
                rising_count = None
                falling_count = None
        except FuturesTimeoutError:
            logger.warning("获取全市场涨跌家数超时，回退到指数涨跌推算（不影响盘后分析主流程）")
            rising_count = None
            falling_count = None
        except Exception as e:
            logger.warning(f"获取全市场数据失败: {str(e)}，使用指数涨跌作为参考")
            rising_count = None
            falling_count = None
        
        # 如果无法获取全市场数据，使用指数涨跌作为参考
        if rising_count is None or falling_count is None:
            logger.debug("使用指数涨跌推算市场情绪（全市场数据不可用）")
            if shanghai_daily is not None and not shanghai_daily.empty:
                latest_change = shanghai_daily['涨跌幅'].iloc[-1] if '涨跌幅' in shanghai_daily.columns else 0
                # 根据指数涨跌幅推算上涨比例
                rising_ratio = 0.5 + (latest_change / 100) * 0.3  # 根据涨跌幅调整，限制在合理范围
                rising_ratio = max(0.2, min(0.8, rising_ratio))  # 限制在0.2-0.8之间
                # 注意：此时 rising_count 和 falling_count 保持为 None，表示数据不可用
                logger.debug(f"根据指数涨跌幅({latest_change:.2f}%)推算上涨比例: {rising_ratio:.2%}")
        
        # 6. 综合判断下一交易日大势
        overall_trend, trend_strength = judge_overall_trend(
            shanghai_trend,
            hs300_trend,
            rising_ratio
        )
        
        # 6. 总结当天日内行情整体情况
        intraday_summary: Dict[str, Any] = {
            "shanghai_change": None,
            "hs300_change": None,
            "volume_status": "正常"  # 放量/缩量/正常
        }
        
        if shanghai_daily is not None and not shanghai_daily.empty:
            if '涨跌幅' in shanghai_daily.columns:
                intraday_summary["shanghai_change"] = float(shanghai_daily['涨跌幅'].iloc[-1])
            # 分析成交量变化（简化处理）
            if '成交量' in shanghai_daily.columns and len(shanghai_daily) >= 2:
                current_volume = shanghai_daily['成交量'].iloc[-1]
                prev_volume = shanghai_daily['成交量'].iloc[-2]
                if prev_volume > 0:
                    volume_change = (current_volume - prev_volume) / prev_volume
                    if volume_change > 0.2:
                        intraday_summary["volume_status"] = "放量"
                    elif volume_change < -0.2:
                        intraday_summary["volume_status"] = "缩量"
        
        if hs300_daily is not None and not hs300_daily.empty:
            if '涨跌幅' in hs300_daily.columns:
                intraday_summary["hs300_change"] = float(hs300_daily['涨跌幅'].iloc[-1])
        
        # 7. 生成分析报告
        report = {
            "date": today,
            "shanghai_trend": shanghai_trend,
            "shanghai_strength": shanghai_strength,
            "hs300_trend": hs300_trend,
            "hs300_strength": hs300_strength,
            "overall_trend": overall_trend,
            "trend_strength": trend_strength,
            "rising_ratio": rising_ratio,
            "rising_count": rising_count,
            "falling_count": falling_count,
            "intraday_summary": intraday_summary,
            "next_day_suggestion": "偏多" if overall_trend == "强势" else ("偏空" if overall_trend == "弱势" else "谨慎")
        }
        if data_stale_warning:
            report["data_stale_warning"] = data_stale_warning
        
        logger.info(f"盘后分析完成: {overall_trend}, 趋势强度: {trend_strength:.2f}")
        return report
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'analyze_daily_market_after_close'},
            "盘后分析失败"
        )
        return {
            "date": datetime.now().strftime("%Y%m%d"),
            "overall_trend": "震荡",
            "trend_strength": 0.5,
            "next_day_suggestion": "谨慎"
        }


def fetch_a50_futures_data() -> Dict[str, Any]:
    """
    获取富时A50期指数据（夜盘）
    
    使用AKShare的futures_foreign_hist接口获取A50期指日线数据。
    数据源：新浪财经（通过AKShare封装）
    
    注意：新浪财经的CN_MarketData.getKLineData接口不支持A50期货数据（返回null），
    但futures_foreign_hist接口可以正常获取A50数据。

    **使用范围**：本函数仅服务于「盘前趋势分析」`analyze_market_before_open`（隔夜指示）。
    盘后 `analyze_daily_market_after_close`、开盘 `analyze_opening_market` **不调用**本函数，
    样本不足或失败时只影响盘前结论，不必在其它分析类型中兜底或重复拉取。
    
    Returns:
        dict: A50数据，包含涨跌幅等
    """
    try:
        # 先近2 个自然日；若筛选后不足 2 条 K 线（周末/节假日/披露延迟），扩至约 25 天取最近两条（与 HXC 扩窗一致）
        today = datetime.now().strftime("%Y%m%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        wide_start = (datetime.now() - timedelta(days=25)).strftime("%Y%m%d")
        logger.info("开始获取A50期指数据: start=%s, end=%s", yesterday, today)

        # 使用AKShare接口获取A50数据（数据源：新浪财经）
        a50_daily = fetch_a50_daily_sina_hist(
            start_date=yesterday,
            end_date=today
        )

        if a50_daily is not None and not a50_daily.empty and len(a50_daily) < 2:
            logger.info("A50主链路近窗仅 %d 条，扩窗拉取: %s~%s", len(a50_daily), wide_start, today)
            a50_daily = fetch_a50_daily_sina_hist(
                start_date=wide_start,
                end_date=today
            )

        if a50_daily is not None and not a50_daily.empty:
            logger.info("A50主链路返回成功: rows=%d", len(a50_daily))
            # 计算涨跌幅
            if len(a50_daily) >= 2:
                prev_close = a50_daily.iloc[-2]['收盘']
                curr_close = a50_daily.iloc[-1]['收盘']
                change_pct = (curr_close - prev_close) / prev_close * 100
                return {
                    'change_pct': change_pct,
                    'status': 'ok',
                    'source': 'fetch_a50_daily_sina_hist'
                }
            logger.warning("A50主链路样本不足: rows=%d (<2)", len(a50_daily))
        else:
            logger.warning("A50主链路返回空数据，准备走工具兜底")

        # 兜底：调用工具层历史接口（fetch_a50.py）
        try:
            from plugins.data_collection.futures.fetch_a50 import tool_fetch_a50_data
            fallback = tool_fetch_a50_data(
                symbol="A50期指",
                data_type="hist",
                start_date=wide_start,
                end_date=today,
                use_cache=True,
            )
            hist_data = (fallback or {}).get("hist_data") or {}
            klines = hist_data.get("klines") or []
            logger.info(
                "A50兜底结果: success=%s, source=%s, kline_count=%d",
                (fallback or {}).get("success"),
                (fallback or {}).get("source"),
                len(klines),
            )
            if len(klines) >= 2:
                prev_close = float(klines[-2].get("close"))
                curr_close = float(klines[-1].get("close"))
                change_pct = (curr_close - prev_close) / prev_close * 100
                return {
                    'change_pct': change_pct,
                    'status': 'ok_fallback',
                    'source': (fallback or {}).get("source", "tool_fetch_a50_data")
                }
            if len(klines) == 1:
                logger.warning("A50兜底样本不足: 仅1条K线，无法计算涨跌幅")
                return {
                    'change_pct': None,
                    'status': 'insufficient_data',
                    'source': (fallback or {}).get("source", "tool_fetch_a50_data"),
                    'reason': 'A50历史样本不足(仅1条)'
                }
        except Exception as fallback_error:
            logger.warning("A50兜底调用异常: %s", str(fallback_error))

        logger.warning("获取A50期指数据失败（主链路+兜底均未得到可计算样本）")
        return {
            'change_pct': None,
            'status': 'failed',
            'reason': '主链路返回空或样本不足，兜底未获取到可计算样本'
        }
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'fetch_a50_futures_data'},
            "获取A50期指数据失败"
        )
        return {'change_pct': None, 'status': 'error', 'reason': str(e)}


def fetch_nasdaq_golden_dragon() -> Dict[str, Any]:
    """
    获取纳斯达克中国金龙指数数据（yfinance ^HXC 历史链路）

    **使用范围**：仅由「盘前趋势分析」`analyze_market_before_open` 调用，作 A50 缺失时的隔夜替补。
    盘后/开盘分析不依赖本链路；遇 yfinance 限流（Too Many Requests）时仅盘前降级为仅靠盘后结论，
    其它趋势分析类型无需考虑该错误。

    Returns:
        dict: HXC数据，包含涨跌幅等
    """
    try:
        # 按用户要求：HXC 不再走 AkShare 全量快照，仅使用 yfinance 历史链路
        # 获取HXC历史数据（先取近2天）
        today = datetime.now().strftime("%Y%m%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        hxc_hist = fetch_global_index_hist_em(
            symbol="纳斯达克中国金龙指数",
            start_date=yesterday,
            end_date=today
        )

        # 如果近2天样本不足，再扩窗口到近10天取最近两条有效交易日
        if hxc_hist is None or hxc_hist.empty or len(hxc_hist) < 2:
            back_start = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
            hxc_hist = fetch_global_index_hist_em(
                symbol="纳斯达克中国金龙指数",
                start_date=back_start,
                end_date=today
            )

        if hxc_hist is None or hxc_hist.empty:
            logger.warning("纳斯达克中国金龙指数历史数据获取失败")
            return {'change_pct': None, 'status': 'failed', 'reason': '历史数据为空'}

        if len(hxc_hist) >= 2:
            close_s = _extract_close_series(hxc_hist)
            if close_s is None or len(close_s) < 2:
                return {'change_pct': None, 'status': 'insufficient_data', 'reason': '收盘列缺失或样本不足'}
            prev_close = float(close_s.iloc[-2])
            curr_close = float(close_s.iloc[-1])
            change_pct = (curr_close - prev_close) / prev_close * 100
            # 更新缓存（按日期存收盘）
            try:
                date_str = _extract_date_yyyymmdd_from_row(hxc_hist.iloc[-1])
                if date_str:
                    cache = _load_hxc_close_cache()
                    cache[date_str] = curr_close
                    _save_hxc_close_cache(cache)
            except Exception:
                pass
            return {'change_pct': change_pct, 'status': 'ok', 'source': 'global_index_hist'}

        # len == 1：尝试使用缓存补齐上一交易日收盘
        try:
            curr_close = _extract_close_from_row(hxc_hist.iloc[-1])
            if curr_close is None:
                return {'change_pct': None, 'status': 'insufficient_data', 'reason': '收盘列缺失'}
            curr_date = _extract_date_yyyymmdd_from_row(hxc_hist.iloc[-1])

            cache = _load_hxc_close_cache()
            if curr_date:
                # 找到严格小于 curr_date 的最近一条
                prev_dates = sorted([d for d in cache.keys() if d < curr_date])
                if prev_dates:
                    prev_date = prev_dates[-1]
                    prev_close = float(cache[prev_date])
                    change_pct = (curr_close - prev_close) / prev_close * 100
                    # 也把当前值写入缓存
                    cache[curr_date] = curr_close
                    _save_hxc_close_cache(cache)
                    return {
                        'change_pct': change_pct,
                        'status': 'ok_cache_prev_close',
                        'source': 'global_index_hist+cache_prev_close',
                        'cache_prev_date': prev_date,
                    }
            # 写入当前 close，供未来使用
            if curr_date:
                cache[curr_date] = curr_close
                _save_hxc_close_cache(cache)
        except Exception:
            pass

        return {'change_pct': None, 'status': 'insufficient_data', 'reason': '历史样本不足(<2)'}
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'fetch_nasdaq_golden_dragon'},
            "获取纳斯达克中国金龙指数数据失败"
        )
        return {'change_pct': None, 'status': 'error', 'reason': str(e)}


def _load_saved_after_close_for_before_open(
    calendar_today: str,
    config: Optional[Dict],
    max_calendar_lookback: int = 10,
) -> Optional[Dict[str, Any]]:
    """
    从 data_storage 落盘加载盘后报告，供盘前复用。
    自 calendar_today 起向前回退若干自然日，取首个含 overall_trend 的文件（覆盖周末后周一等场景）。
    """
    try:
        from src.data_storage import load_trend_analysis

        base = datetime.strptime(calendar_today, "%Y%m%d")
        for i in range(max_calendar_lookback):
            d = (base - timedelta(days=i)).strftime("%Y%m%d")
            data = load_trend_analysis(date=d, analysis_type="after_close", config=config)
            if isinstance(data, dict) and data.get("overall_trend") is not None:
                return data
    except Exception as e:
        logger.debug("加载落盘盘后报告失败: %s", e, exc_info=True)
    return None


def analyze_market_before_open(
    after_close_report: Optional[Dict] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    每天开盘前9:15执行
    结合前晚外盘行情，作出当天行情整体趋势判断

    **隔夜数据边界**：富时 A50 与纳斯达克中国金龙（HXC）仅在本流程中拉取与解释；
    盘后分析与开盘分析均不调用上述接口，也不承担其样本不足 / yfinance 限流带来的语义。
    若隔夜数据不可用，见 `overnight_overlay_degraded` 与日志，并回退为盘后结论加权。
    
    Args:
        after_close_report: 盘后分析结果；若为 None，则优先读当日及近日的 after_close 落盘，
            无文件时再现场执行 analyze_daily_market_after_close（避免与已跑过的盘后重复计算）。
        config: 系统配置
    
    Returns:
        dict: 开盘策略建议（含 after_close_basis: passed | disk | computed）
    """
    try:
        logger.info("开始开盘前分析...")
        
        today = datetime.now(pytz.timezone('Asia/Shanghai')).strftime("%Y%m%d")
        
        # 1. 盘后结论：显式传入 > 落盘复用 > 现场计算
        after_close_basis = "passed"
        if after_close_report is None:
            saved = _load_saved_after_close_for_before_open(today, config)
            if saved is not None:
                after_close_report = saved
                after_close_basis = "disk"
                logger.info(
                    "未提供盘后分析结果，已使用落盘 after_close（报告内 date=%s）",
                    saved.get("date", "?"),
                )
            else:
                logger.info("无可用盘后落盘，现场执行盘后分析...")
                after_close_report = analyze_daily_market_after_close(config)
                after_close_basis = "computed"
        
        # 2. 隔夜外盘（仅盘前）：A50 主链 + 金龙替补；失败则 final 趋势回退盘后（不影响盘后/开盘其它入口）
        # change_pct 缺省不得用 0，否则误判阈值分支
        a50_data = fetch_a50_futures_data()
        a50_change = a50_data.get("change_pct")

        hxc_data = fetch_nasdaq_golden_dragon()
        hxc_change = hxc_data.get("change_pct")

        # 3. 综合判断（结合盘后+外盘）；优先 A50，缺失时用金龙指数同阈值
        after_close_trend = after_close_report.get('overall_trend', '震荡')
        after_close_strength = after_close_report.get('trend_strength', 0.5)

        effective_overnight = a50_change
        if effective_overnight is None and hxc_change is not None:
            effective_overnight = hxc_change

        # 外盘影响分析
        if effective_overnight is None:
            logger.warning("A50/金龙隔夜涨跌幅均不可用，仅使用盘后分析结果（可依赖工作流 tavily 摘要合并 report_data）")
            final_trend = after_close_trend
            final_strength = after_close_strength * 0.8
        elif effective_overnight > 0.5:
            if after_close_trend == "强势":
                final_trend = "强势"
                final_strength = 1.0
            elif after_close_trend == "弱势":
                final_trend = "震荡"
                final_strength = 0.5
            else:
                final_trend = "震荡"
                final_strength = 0.6
        elif effective_overnight < -0.5:
            if after_close_trend == "弱势":
                final_trend = "弱势"
                final_strength = 1.0
            elif after_close_trend == "强势":
                final_trend = "震荡"
                final_strength = 0.5
            else:
                final_trend = "震荡"
                final_strength = 0.6
        else:
            final_trend = after_close_trend
            final_strength = after_close_strength * 0.9

        # 4. 生成开盘策略建议
        strategy_suggestion = generate_opening_strategy(final_trend, final_strength)

        overnight_overlay_degraded = effective_overnight is None

        result: Dict[str, Any] = {
            "date": today,
            "after_close_basis": after_close_basis,
            "after_close_trend": after_close_trend,
            "a50_change": a50_change,
            "hxc_change": hxc_change,
            "effective_overnight_change": effective_overnight,
            "a50_status": a50_data.get("status"),
            "hxc_status": hxc_data.get("status"),
            "a50_reason": a50_data.get("reason"),
            "hxc_reason": hxc_data.get("reason"),
            "final_trend": final_trend,
            "final_strength": final_strength,
            "opening_strategy": strategy_suggestion,
            "overnight_overlay_degraded": overnight_overlay_degraded,
        }

        a50_str = f"{a50_change:.2f}%" if a50_change is not None else "N/A"
        logger.info(f"开盘前分析完成: {final_trend}, 趋势强度: {final_strength:.2f}, A50: {a50_str}")
        return result
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'analyze_market_before_open'},
            "开盘前分析失败"
        )
        return {
            "date": datetime.now().strftime("%Y%m%d"),
            "after_close_basis": "error",
            "final_trend": "震荡",
            "final_strength": 0.5,
            "opening_strategy": generate_opening_strategy("震荡", 0.5)
        }


def generate_opening_strategy(trend: str, strength: float) -> Dict[str, Any]:
    """
    根据趋势判断生成开盘策略建议
    
    Args:
        trend: 趋势方向
        strength: 趋势强度
    
    Returns:
        dict: 策略建议
    """
    try:
        if trend == "强势" and strength >= 0.8:
            return {
                "direction": "偏多",
                "suggest_call": True,
                "suggest_put": False,
                "position_size": "中等",
                "signal_threshold": "正常"
            }
        elif trend == "弱势" and strength >= 0.8:
            return {
                "direction": "偏空",
                "suggest_call": False,
                "suggest_put": True,
                "position_size": "中等",
                "signal_threshold": "正常"
            }
        else:
            return {
                "direction": "谨慎",
                "suggest_call": True,
                "suggest_put": True,
                "position_size": "较小",
                "signal_threshold": "提高"
            }
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'generate_opening_strategy', 'trend': trend, 'strength': strength},
            "生成开盘策略失败"
        )
        return {
            "direction": "谨慎",
            "suggest_call": True,
            "suggest_put": True,
            "position_size": "较小",
            "signal_threshold": "提高"
        }


def analyze_opening_market(
    opening_data: Dict[str, Dict[str, Any]],
    historical_data: Optional[Dict[str, Dict[str, Any]]] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    分析开盘行情，计算各指数的开盘强度
    
    Args:
        opening_data: 开盘数据（来自fetch_index_opening_data）
        historical_data: 历史数据（可选，如果为None则自动获取）
        config: 系统配置
    
    Returns:
        dict: 格式 {
            "上证": {
                "change_pct": 0.08,
                "vol_dev": 0.05,  # 成交量偏差
                "hist_dev": -0.1,  # 历史偏差
                "strength_score": 0.3,
                "strength": "中性"
            },
            ...
            "summary": {
                "strong_count": 2,
                "weak_count": 1,
                "neutral_count": 3
            }
        }
    """
    try:
        logger.info("开始分析开盘行情...")
        
        # 获取配置
        if config is None:
            from src.config_loader import load_system_config
            config = load_system_config(use_cache=True)
        
        opening_config = config.get('opening_analysis', {})
        lookback_days = opening_config.get('lookback_days', 5)
        strength_threshold = opening_config.get('strength_threshold', {})
        strong_threshold = strength_threshold.get('strong', 0.5)
        weak_threshold = strength_threshold.get('weak', -0.5)
        
        analysis = {}
        
        # 如果historical_data为None，自动获取历史数据
        if historical_data is None:
            historical_data = {}
            for name, data in opening_data.items():
                code = data.get('code')
                if code:
                    logger.debug(f"获取{name}({code})的历史数据...")
                    hist_df = fetch_index_opening_history(code, lookback_days)
                    if hist_df is not None and not hist_df.empty:
                        # 计算历史均值
                        if '开盘涨跌幅' in hist_df.columns:
                            mean_open_change = hist_df['开盘涨跌幅'].mean()
                        else:
                            # 如果没有开盘涨跌幅，从开盘和昨收计算
                            if '开盘' in hist_df.columns and '昨收' in hist_df.columns:
                                hist_df['开盘涨跌幅'] = (
                                    (hist_df['开盘'] - hist_df['昨收']) / hist_df['昨收'] * 100
                                )
                                mean_open_change = hist_df['开盘涨跌幅'].mean()
                            else:
                                mean_open_change = 0.0
                        
                        # 计算成交量均值
                        vol_col = None
                        for col in ['成交量', 'volume', 'vol']:
                            if col in hist_df.columns:
                                vol_col = col
                                break
                        
                        mean_volume = hist_df[vol_col].mean() if vol_col else 0.0
                        
                        historical_data[name] = {
                            'mean_open_change': mean_open_change,
                            'mean_volume': mean_volume
                        }
                    else:
                        historical_data[name] = {
                            'mean_open_change': 0.0,
                            'mean_volume': 0.0
                        }
                        logger.warning(f"无法获取{name}的历史数据，使用默认值")
        
        # 分析每个指数
        for name, data in opening_data.items():
            # 插件 fetch_index_opening 使用 opening_price / pre_close；历史字段为 open_price / close_yesterday
            open_price = data.get('open_price')
            if open_price is None:
                open_price = data.get('opening_price')
            close_yesterday = data.get('close_yesterday')
            if close_yesterday is None:
                close_yesterday = data.get('pre_close')
            change_pct = data.get('change_pct')
            volume = data.get('volume')
            
            # 如果change_pct为None，计算涨幅
            if change_pct is None and open_price is not None and close_yesterday is not None:
                change_pct = (open_price - close_yesterday) / close_yesterday * 100

            try:
                from plugins.utils.index_pct_sanity import reconcile_index_change_pct

                if open_price is not None and close_yesterday is not None:
                    rp = reconcile_index_change_pct(change_pct, open_price, close_yesterday)
                    if rp is not None:
                        change_pct = rp
            except ImportError:
                pass
            
            # 获取历史数据
            hist_data = historical_data.get(name, {})
            mean_open_change = hist_data.get('mean_open_change', 0.0)
            mean_volume = hist_data.get('mean_volume', 0.0)
            
            # 计算成交量偏差
            if volume is not None and mean_volume > 0:
                vol_dev = (volume - mean_volume) / mean_volume
            else:
                vol_dev = 0.0
            
            # 计算历史偏差
            if change_pct is not None:
                hist_dev = change_pct - mean_open_change
            else:
                hist_dev = 0.0
            
            # 计算强度分数
            # 涨幅权重50% + 成交偏差30% + 历史偏差20%
            # 注意：涨幅需要归一化（假设正常涨幅在-2%到+2%之间）
            normalized_change = (change_pct / 2.0) if change_pct is not None else 0.0
            # 限制在合理范围内
            normalized_change = max(-1.0, min(1.0, normalized_change))
            
            strength_score = normalized_change * 0.5 + vol_dev * 0.3 + (hist_dev / 2.0) * 0.2
            
            # 判断强度
            if strength_score > strong_threshold:
                strength = "强势"
            elif strength_score < weak_threshold:
                strength = "弱势"
            else:
                strength = "中性"
            
            analysis[name] = {
                "change_pct": change_pct,
                "vol_dev": vol_dev,
                "hist_dev": hist_dev,
                "strength_score": strength_score,
                "strength": strength,
                "open_price": open_price,
                "close_yesterday": close_yesterday,
                "volume": volume
            }
            
            _cp_dbg = f"{change_pct:.2f}" if change_pct is not None else "N/A"
            logger.debug(
                f"{name}开盘分析: 涨幅={_cp_dbg}%, 成交偏差={vol_dev:.2%}, "
                f"历史偏差={hist_dev:.2f}%, 强度分数={strength_score:.2f}, 强度={strength}"
            )
        
        # 统计汇总
        strong_count = sum(1 for a in analysis.values() if a.get('strength') == '强势')
        weak_count = sum(1 for a in analysis.values() if a.get('strength') == '弱势')
        neutral_count = sum(1 for a in analysis.values() if a.get('strength') == '中性')
        
        analysis['summary'] = {
            "strong_count": strong_count,
            "weak_count": weak_count,
            "neutral_count": neutral_count,
            "total_count": len(analysis) - 1  # 减去summary本身
        }
        
        logger.info(f"开盘分析完成: 强势{strong_count}个, 弱势{weak_count}个, 中性{neutral_count}个")
        return analysis
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'analyze_opening_market',
                'opening_data_keys': list(opening_data.keys()) if opening_data else []
            },
            "分析开盘行情失败"
        )
        return {
            "summary": {
                "strong_count": 0,
                "weak_count": 0,
                "neutral_count": 0,
                "total_count": 0
            }
        }


def predict_daily_trend_from_opening(
    opening_analysis: Dict[str, Any],
    config: Optional[Dict] = None,
    use_arima: bool = True
) -> Dict[str, Any]:
    """
    基于开盘分析预测当天趋势（集成ARIMA优化）
    
    Args:
        opening_analysis: 开盘分析结果（来自analyze_opening_market）
        config: 系统配置
        use_arima: 是否使用ARIMA预测（默认True）
    
    Returns:
        dict: 格式 {
            "trend": "上行",  # 或 "下行" / "震荡"
            "confidence": 0.65,  # 置信度 0-1
            "weighted_score": 0.3,
            "strong_indices": ["沪深300", "上证"],
            "weak_indices": ["北证50"],
            "reasoning": "沪深300和上证开盘强势，加权分数0.3，预测上行",
            "arima_enhanced": True,  # 是否使用了ARIMA增强
            "arima_trend": "上行",   # ARIMA预测的趋势
            "arima_confidence": 0.75  # ARIMA置信度
        }
    """
    try:
        logger.info("开始预测当天趋势（集成ARIMA）...")
        
        # 获取配置
        if config is None:
            from src.config_loader import load_system_config
            config = load_system_config(use_cache=True)
        
        opening_config = config.get('opening_analysis', {})
        weights = opening_config.get('weights', {
            "沪深300": 0.3,
            "上证": 0.2,
            "深成指": 0.15,
            "创业板": 0.15,
            "科创综指": 0.1,
            "北证50": 0.1
        })
        
        trend_threshold = opening_config.get('trend_threshold', {})
        up_threshold = trend_threshold.get('up', 0.3)
        down_threshold = trend_threshold.get('down', -0.3)
        
        # 获取汇总信息
        summary = opening_analysis.get('summary', {})
        strong_count = summary.get('strong_count', 0)
        weak_count = summary.get('weak_count', 0)
        total_count = summary.get('total_count', 0)
        
        # 计算加权分数
        weighted_score = 0.0
        strong_indices = []
        weak_indices = []
        neutral_indices = []
        
        for name, data in opening_analysis.items():
            if name == 'summary':
                continue
            
            strength = data.get('strength', '中性')
            weight = weights.get(name, 0.0)
            
            if strength == '强势':
                weighted_score += weight * 1.0
                strong_indices.append(name)
            elif strength == '弱势':
                weighted_score += weight * -1.0
                weak_indices.append(name)
            else:
                neutral_indices.append(name)
        
        # ========== 新增：ARIMA增强预测 ==========
        arima_trend = None
        arima_confidence = 0.5
        arima_enhanced = False
        
        if use_arima:
            try:
                from src.trend_analyzer_arima import predict_index_trend_arima
                from src.data_collector import fetch_index_daily_em
                from datetime import datetime, timedelta
                
                # 获取沪深300的日线数据（优先使用，权重最高）
                hs300_code = "000300"
                # 获取最近250天的数据（足够ARIMA使用）
                end_date = datetime.now().strftime("%Y%m%d")
                start_date = (datetime.now() - timedelta(days=250)).strftime("%Y%m%d")
                daily_df = fetch_index_daily_em(hs300_code, period="daily", start_date=start_date, end_date=end_date)
                
                if daily_df is not None and not daily_df.empty and len(daily_df) >= 30:
                    # 使用ARIMA预测（1天，因为开盘分析是预测当天）
                    arima_result = predict_index_trend_arima(
                        daily_df,
                        forecast_days=1,  # 开盘分析预测当天
                        auto_select_order=True,
                        data_window_days=200,
                        use_volume=True,  # 开盘分析使用成交量特征
                        volume_df=daily_df if '成交量' in daily_df.columns else None
                    )
                    
                    if arima_result and not arima_result.get('error'):
                        arima_trend = arima_result.get('direction', '震荡')
                        arima_confidence = arima_result.get('confidence', 0.5)
                        arima_enhanced = True
                        
                        logger.info(f"ARIMA开盘预测: {arima_trend}, 置信度: {arima_confidence:.2f}")
            except Exception as e:
                logger.debug(f"ARIMA开盘预测失败: {e}，仅使用开盘分析")
        
        # 投票机制：强势指数>4个 → 上行；弱势>4个 → 下行；否则看加权分数
        opening_trend = None
        opening_confidence = 0.5
        
        if strong_count > 4:
            opening_trend = "上行"
            opening_confidence = min(0.9, 0.5 + (strong_count / total_count) * 0.4) if total_count > 0 else 0.5
        elif weak_count > 4:
            opening_trend = "下行"
            opening_confidence = min(0.9, 0.5 + (weak_count / total_count) * 0.4) if total_count > 0 else 0.5
        else:
            # 根据加权分数判断
            if weighted_score > up_threshold:
                opening_trend = "上行"
            elif weighted_score < down_threshold:
                opening_trend = "下行"
            else:
                opening_trend = "震荡"
            
            # 计算置信度（基于加权分数的绝对值）
            total_weight = sum(weights.values())
            if total_weight > 0:
                opening_confidence = min(0.9, abs(weighted_score) / total_weight)
            else:
                opening_confidence = 0.5
        
        # 融合ARIMA和开盘分析（如果ARIMA可用）
        if arima_enhanced and arima_trend:
            # ARIMA权重60%，开盘分析权重40%
            arima_weight = 0.6
            opening_weight = 0.4
            
            # 趋势方向映射
            trend_scores = {
                "上行": 1.0,
                "强势": 1.0,
                "震荡": 0.5,
                "弱势": 0.0,
                "下行": 0.0
            }
            
            arima_score = trend_scores.get(arima_trend, 0.5)
            opening_score = trend_scores.get(opening_trend, 0.5)
            
            combined_score = arima_score * arima_weight + opening_score * opening_weight
            combined_confidence = arima_confidence * arima_weight + opening_confidence * opening_weight
            
            # 判断最终趋势
            if combined_score >= 0.7:
                trend = "上行"
            elif combined_score <= 0.3:
                trend = "下行"
            else:
                trend = "震荡"
            
            confidence = combined_confidence
            reasoning = f"ARIMA预测{arima_trend}(置信度{arima_confidence:.2f}) + 开盘分析{opening_trend}(置信度{opening_confidence:.2f})，综合预测{trend}"
        else:
            # 仅使用开盘分析
            trend = opening_trend
            confidence = opening_confidence
            reasoning = f"加权分数{weighted_score:.2f}，"
            if strong_indices:
                reasoning += f"{'、'.join(strong_indices)}开盘强势，"
            if weak_indices:
                reasoning += f"{'、'.join(weak_indices)}开盘弱势，"
            reasoning += f"预测{trend}"
        
        result: Dict[str, Any] = {
            "trend": trend,
            "confidence": confidence,
            "weighted_score": weighted_score,
            "strong_indices": strong_indices,
            "weak_indices": weak_indices,
            "neutral_indices": neutral_indices,
            "strong_count": strong_count,
            "weak_count": weak_count,
            "neutral_count": summary.get('neutral_count', 0),
            "reasoning": reasoning,
            "arima_enhanced": arima_enhanced,
            "arima_trend": arima_trend,
            "arima_confidence": arima_confidence,
            "opening_trend": opening_trend,
            "opening_confidence": opening_confidence,
        }

        logger.info(
            f"趋势预测: {trend} (置信度: {confidence:.2%}), "
            f"ARIMA增强: {arima_enhanced}, 加权分数: {weighted_score:.2f}"
        )
        return result
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'predict_daily_trend_from_opening',
                'opening_analysis_keys': list(opening_analysis.keys()) if opening_analysis else []
            },
            "预测当天趋势失败"
        )
        return {
            "trend": "震荡",
            "confidence": 0.5,
            "weighted_score": 0.0,
            "strong_indices": [],
            "weak_indices": [],
            "neutral_indices": [],
            "reasoning": "分析失败，默认震荡"
        }
