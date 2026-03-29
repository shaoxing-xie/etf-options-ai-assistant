"""
策略效果跟踪插件
记录信号效果，评估策略表现
扩展原系统 prediction_recorder.py
OpenClaw 插件工具
"""

import sys
import json
import sqlite3
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)

# journal（追加写入，不影响原有 JSON/SQLite）
try:
    from src.trading_journal import append_journal_event
    JOURNAL_AVAILABLE = True
except Exception as _:
    JOURNAL_AVAILABLE = False

    def append_journal_event(*args, **kwargs):  # type: ignore[no-redef]
        return False

# 尝试将当前环境中的本地 src 根目录加入 Python 路径
selected_root: Optional[Path] = None
for parent in Path(__file__).resolve().parents:
    if (parent / "src").exists():
        selected_root = parent
        break
if selected_root is not None and str(selected_root) not in sys.path:
    sys.path.insert(0, str(selected_root))

# 兼容：原系统模块可能不存在；当前插件只依赖本地实现

# 信号记录存储路径（使用绝对路径）
BASE_DIR = Path(__file__).parent.parent.parent
SIGNAL_RECORDS_DIR = BASE_DIR / "data" / "signal_records"
SIGNAL_DB_PATH = SIGNAL_RECORDS_DIR / "signal_records.db"


def record_signal_effect(
    signal_id: str,
    signal_type: str,  # 'buy' | 'sell' | 'call' | 'put'
    etf_symbol: str,
    signal_strength: float,
    strategy: str,  # 'trend_following' | 'mean_reversion' | 'breakout'
    entry_price: float,
    exit_price: Optional[float] = None,
    profit_loss: Optional[float] = None,
    profit_loss_pct: Optional[float] = None,
    holding_days: Optional[int] = None,
    status: str = 'pending',  # 'pending' | 'executed' | 'closed'
    exit_reason: Optional[str] = None,
    journal_extra: Optional[Dict] = None,
) -> bool:
    """
    记录信号效果
    
    Args:
        signal_id: 信号唯一ID
        signal_type: 信号类型
        etf_symbol: ETF代码
        signal_strength: 信号强度
        strategy: 策略名称
        entry_price: 入场价格
        exit_price: 出场价格（可选）
        profit_loss: 盈亏金额（可选）
        profit_loss_pct: 盈亏比例（可选）
        holding_days: 持仓天数（可选）
        status: 状态
        exit_reason: 出场原因（可选）
    
    Returns:
        bool: 是否成功记录
    """
    try:
        # 确保目录存在
        SIGNAL_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
        
        # 获取当前日期
        tz_shanghai = pytz.timezone('Asia/Shanghai')
        now = datetime.now(tz_shanghai)
        date_str = now.strftime('%Y%m%d')
        
        # 构建记录
        record = {
            'signal_id': signal_id,
            'date': date_str,
            'timestamp': now.isoformat(),
            'signal_type': signal_type,
            'etf_symbol': etf_symbol,
            'signal_strength': signal_strength,
            'strategy': strategy,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'profit_loss': profit_loss,
            'profit_loss_pct': profit_loss_pct,
            'holding_days': holding_days,
            'status': status,
            'exit_reason': exit_reason
        }
        
        # 保存到JSON文件（按日期）
        json_file = SIGNAL_RECORDS_DIR / f"signals_{date_str}.json"
        
        # 读取现有记录
        if json_file.exists():
            with open(json_file, 'r', encoding='utf-8') as f:
                records = json.load(f)
        else:
            records = []
        
        # 检查是否已存在（更新或新增）
        existing_index = None
        existing_record = None
        for i, r in enumerate(records):
            if r.get('signal_id') == signal_id:
                existing_index = i
                existing_record = r
                break
        
        if existing_index is not None:
            # 更新现有记录：合并新字段和旧字段
            # 先保留原有字段，然后用新字段覆盖
            merged_record = existing_record.copy()
            merged_record.update(record)
            # 保持原有日期和timestamp（除非明确提供了新的）
            if 'date' in existing_record and 'date' not in record:
                merged_record['date'] = existing_record['date']
            if 'timestamp' in existing_record and 'timestamp' not in record:
                merged_record['timestamp'] = existing_record['timestamp']
            records[existing_index] = merged_record
            # 使用合并后的记录保存到数据库
            record = merged_record
        else:
            records.append(record)
        
        # 保存
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        
        # 同时保存到SQLite数据库
        _save_to_database(record)

        # 追加写入统一 journal（不破坏旧逻辑；失败不影响主流程）
        if JOURNAL_AVAILABLE:
            try:
                jp: Dict[str, Any] = {
                    "signal_id": record.get("signal_id"),
                    "date": record.get("date"),
                    "timestamp": record.get("timestamp"),
                    "signal_type": record.get("signal_type"),
                    "symbol": record.get("etf_symbol"),
                    "signal_strength": record.get("signal_strength"),
                    "strategy": record.get("strategy"),
                    "entry_price": record.get("entry_price"),
                    "exit_price": record.get("exit_price"),
                    "profit_loss": record.get("profit_loss"),
                    "profit_loss_pct": record.get("profit_loss_pct"),
                    "holding_days": record.get("holding_days"),
                    "status": record.get("status"),
                    "exit_reason": record.get("exit_reason"),
                    "source": "strategy_tracker",
                }
                if journal_extra and isinstance(journal_extra, dict):
                    jp = {**jp, **journal_extra}
                append_journal_event(
                    "signal_recorded",
                    jp,
                    actor="tool_record_signal_effect",
                    base_dir=BASE_DIR,
                )
            except Exception as _:
                logger.debug("JOURNAL append failed", exc_info=True)
        
        return True
        
    except Exception as _:
        return False


def _save_to_database(record: dict):
    """保存到SQLite数据库"""
    try:
        conn = sqlite3.connect(SIGNAL_DB_PATH)
        cursor = conn.cursor()
        
        # 创建表（如果不存在）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signal_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT UNIQUE NOT NULL,
                date TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                etf_symbol TEXT NOT NULL,
                signal_strength REAL,
                strategy TEXT,
                entry_price REAL,
                exit_price REAL,
                profit_loss REAL,
                profit_loss_pct REAL,
                holding_days INTEGER,
                status TEXT,
                exit_reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 插入或更新记录
        cursor.execute('''
            INSERT OR REPLACE INTO signal_records (
                signal_id, date, timestamp, signal_type, etf_symbol,
                signal_strength, strategy, entry_price, exit_price,
                profit_loss, profit_loss_pct, holding_days, status, exit_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            record['signal_id'],
            record['date'],
            record['timestamp'],
            record['signal_type'],
            record['etf_symbol'],
            record['signal_strength'],
            record['strategy'],
            record['entry_price'],
            record.get('exit_price'),
            record.get('profit_loss'),
            record.get('profit_loss_pct'),
            record.get('holding_days'),
            record['status'],
            record.get('exit_reason')
        ))
        
        conn.commit()
        conn.close()
        
    except Exception as _:
        logger.debug("SQLite save failed, ignore", exc_info=True)


def _validate_yyyymmdd(s: str) -> str:
    s = (s or "").strip()
    if len(s) != 8 or not s.isdigit():
        raise ValueError(f"date must be YYYYMMDD, got {s!r}")
    return s


def _resolve_date_bounds(
    lookback_days: int,
    start_date: Optional[str],
    end_date: Optional[str],
    tz_shanghai: Any,
) -> Tuple[str, str]:
    """Resolve inclusive [start_date, end_date] as YYYYMMDD strings."""
    now = datetime.now(tz_shanghai)
    today_s = now.strftime("%Y%m%d")
    end_s = _validate_yyyymmdd(end_date) if (end_date and str(end_date).strip()) else today_s
    if start_date and str(start_date).strip():
        start_s = _validate_yyyymmdd(str(start_date))
    else:
        end_dt = datetime.strptime(end_s, "%Y%m%d")
        start_dt = end_dt - timedelta(days=int(lookback_days))
        start_s = start_dt.strftime("%Y%m%d")
    if start_s > end_s:
        start_s, end_s = end_s, start_s
    return start_s, end_s


def _span_calendar_days(start_s: str, end_s: str) -> int:
    a = datetime.strptime(start_s, "%Y%m%d")
    b = datetime.strptime(end_s, "%Y%m%d")
    return max(1, (b - a).days + 1)


def _per_trade_cost_pct(trading_costs: Optional[Dict[str, Any]]) -> float:
    if not trading_costs or not isinstance(trading_costs, dict):
        return 0.0
    if not trading_costs.get("enabled", False):
        return 0.0
    c = float(trading_costs.get("commission") or 0.0)
    s = float(trading_costs.get("slippage") or 0.0)
    return 2.0 * c + s


def _sharpe_like(returns: List[float]) -> float:
    if len(returns) < 2:
        return 0.0
    m = sum(returns) / len(returns)
    var = sum((x - m) ** 2 for x in returns) / (len(returns) - 1)
    std = var ** 0.5
    if std < 1e-12:
        return 0.0
    return m / std


def _ensure_regime_labels_table(cursor: sqlite3.Cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS signal_regime_labels (
            signal_id TEXT PRIMARY KEY NOT NULL,
            market_regime TEXT NOT NULL
        )
        """
    )


def get_strategy_performance(
    strategy: str,
    lookback_days: int = 60,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    trading_costs: Optional[Dict[str, Any]] = None,
    by_regime: bool = False,
) -> Dict[str, Any]:
    """
    获取策略表现

    Args:
        strategy: 策略名称
        lookback_days: 回看天数（当未指定 start_date 时，从 end_date 或今天向前回溯）
        start_date: 可选，起始日 YYYYMMDD（含）
        end_date: 可选，结束日 YYYYMMDD（含）；默认今天（上海时区）
        trading_costs: 可选 {"enabled": bool, "commission": float, "slippage": float}，对闭合交易按笔扣减
        by_regime: 为 True 时按 signal_regime_labels 表 JOIN 分组（无标签则为 unlabeled）

    Returns:
        dict: 策略表现统计（含 gross/net 与 sharpe_like 等研究级字段）
    """
    try:
        tz_shanghai = pytz.timezone("Asia/Shanghai")
        start_s, end_s = _resolve_date_bounds(
            lookback_days, start_date, end_date, tz_shanghai
        )
        span_days = _span_calendar_days(start_s, end_s)
        cost_pct = _per_trade_cost_pct(trading_costs)

        conn = sqlite3.connect(SIGNAL_DB_PATH)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) as closed,
                SUM(CASE WHEN status = 'closed' AND profit_loss_pct IS NOT NULL
                    AND (profit_loss_pct - ?) > 0 THEN 1 ELSE 0 END) as wins,
                AVG(CASE WHEN status = 'closed' AND profit_loss_pct IS NOT NULL THEN profit_loss_pct ELSE NULL END) as avg_gross,
                AVG(signal_strength) as avg_strength,
                SUM(CASE WHEN status = 'closed' AND profit_loss_pct IS NOT NULL THEN profit_loss_pct ELSE 0 END) as sum_gross,
                SUM(CASE WHEN status = 'closed' AND profit_loss_pct IS NOT NULL THEN (profit_loss_pct - ?) ELSE 0 END) as sum_net
            FROM signal_records
            WHERE strategy = ?
            AND date >= ?
            AND date <= ?
            """,
            (cost_pct, cost_pct, strategy, start_s, end_s),
        )
        row = cursor.fetchone()
        total, closed, wins, avg_gross, avg_strength, sum_gross, sum_net = row

        cursor.execute(
            """
            SELECT profit_loss_pct FROM signal_records
            WHERE strategy = ? AND date >= ? AND date <= ?
            AND status = 'closed' AND profit_loss_pct IS NOT NULL
            ORDER BY date ASC, id ASC
            """,
            (strategy, start_s, end_s),
        )
        gross_returns = [float(r[0]) for r in cursor.fetchall()]
        net_returns = [r - cost_pct for r in gross_returns]

        gross_sharpe_like = _sharpe_like(gross_returns)
        net_sharpe_like = _sharpe_like(net_returns) if cost_pct > 0 else gross_sharpe_like

        closed_n = int(closed or 0)
        sum_g = float(sum_gross or 0.0)
        sum_n = float(sum_net or 0.0)
        annualized_return_proxy_gross = (sum_g / float(span_days)) * 365.0
        annualized_return_proxy_net = (sum_n / float(span_days)) * 365.0

        regime_breakdown: Optional[List[Dict[str, Any]]] = None
        if by_regime:
            _ensure_regime_labels_table(cursor)
            cursor.execute(
                """
                SELECT COALESCE(l.market_regime, 'unlabeled') AS rg,
                    COUNT(*) AS total,
                    SUM(CASE WHEN sr.status = 'closed' THEN 1 ELSE 0 END) AS closed_cnt,
                    SUM(CASE WHEN sr.status = 'closed' AND sr.profit_loss_pct IS NOT NULL
                        AND (sr.profit_loss_pct - ?) > 0 THEN 1 ELSE 0 END) AS wins_c,
                    AVG(CASE WHEN sr.status = 'closed' AND sr.profit_loss_pct IS NOT NULL
                        THEN sr.profit_loss_pct ELSE NULL END) AS avg_g
                FROM signal_records sr
                LEFT JOIN signal_regime_labels l ON sr.signal_id = l.signal_id
                WHERE sr.strategy = ? AND sr.date >= ? AND sr.date <= ?
                GROUP BY rg
                ORDER BY rg
                """,
                (cost_pct, strategy, start_s, end_s),
            )
            regime_breakdown = []
            for rg, t, cl, wn, av in cursor.fetchall():
                cl = int(cl or 0)
                regime_breakdown.append(
                    {
                        "regime": rg,
                        "total_signals": int(t or 0),
                        "closed_signals": cl,
                        "win_rate": float(wn) / cl if cl > 0 else 0.0,
                        "avg_return": float(av) if av is not None else 0.0,
                    }
                )

        conn.close()

        avg_ret = float(avg_gross) if avg_gross is not None else 0.0
        avg_net = (sum_n / closed_n) if closed_n > 0 and cost_pct > 0 else avg_ret

        base: Dict[str, Any] = {
            "success": True,
            "strategy": strategy,
            "start_date": start_s,
            "end_date": end_s,
            "span_calendar_days": span_days,
            "total_signals": int(total or 0),
            "closed_signals": closed_n,
            "win_rate": float(wins) / closed_n if closed_n > 0 else 0.0,
            "avg_return": avg_ret,
            "avg_signal_strength": float(avg_strength) if avg_strength is not None else 0.0,
            "lookback_days": int(lookback_days),
            "sum_closed_return_gross": sum_g,
            "sum_closed_return_net": sum_n,
            "annualized_return_proxy_gross": annualized_return_proxy_gross,
            "annualized_return_proxy_net": annualized_return_proxy_net,
            "gross_sharpe_like": gross_sharpe_like,
            "net_sharpe_like": net_sharpe_like,
            "trading_costs_applied": cost_pct > 0,
            "trading_cost_per_trade_pct": cost_pct,
        }
        if regime_breakdown is not None:
            base["by_regime"] = regime_breakdown
            base["regime_note"] = (
                "按 signal_regime_labels 关联；无记录的标签为 unlabeled。"
            )

        if int(total or 0) == 0:
            base["message"] = "数据不足"
            base["win_rate"] = 0.0
            base["avg_return"] = 0.0
            base["gross_sharpe_like"] = 0.0
            base["net_sharpe_like"] = 0.0
            base["annualized_return_proxy_gross"] = 0.0
            base["annualized_return_proxy_net"] = 0.0

        return base

    except Exception as e:
        return {"success": False, "error": str(e)}


# OpenClaw 工具函数接口
def tool_record_signal_effect(
    signal_id: str,
    signal_type: Optional[str] = None,
    etf_symbol: Optional[str] = None,
    signal_strength: Optional[float] = None,
    strategy: Optional[str] = None,
    entry_price: Optional[float] = None,
    exit_price: Optional[float] = None,
    profit_loss: Optional[float] = None,
    profit_loss_pct: Optional[float] = None,
    holding_days: Optional[int] = None,
    status: Optional[str] = None,
    exit_reason: Optional[str] = None,
    journal_extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """OpenClaw 工具：记录信号效果（支持部分更新）"""
    try:
        # 尝试从数据库读取现有记录
        existing_record = None
        try:
            conn = sqlite3.connect(SIGNAL_DB_PATH)
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM signal_records WHERE signal_id = ?', (signal_id,))
            row = cursor.fetchone()
            if row:
                # 构建现有记录字典
                columns = [desc[0] for desc in cursor.description]
                existing_record = dict(zip(columns, row))
            conn.close()
        except Exception as e:
            logger.debug(f"Failed to load existing record, ignore: {e}", exc_info=True)
        
        # 如果存在现有记录，使用现有值填充缺失字段
        if existing_record:
            if signal_type is None:
                signal_type = existing_record.get('signal_type')
            if etf_symbol is None:
                etf_symbol = existing_record.get('etf_symbol')
            if signal_strength is None:
                signal_strength = existing_record.get('signal_strength', 0.5)
            if strategy is None:
                strategy = existing_record.get('strategy', 'trend_following')
            if entry_price is None:
                entry_price = existing_record.get('entry_price', 0.0)
            if status is None:
                status = existing_record.get('status', 'pending')
        else:
            # 新记录，所有必需字段必须有值
            if signal_type is None or etf_symbol is None or signal_strength is None or strategy is None or entry_price is None:
                return {
                    'success': False,
                    'message': '新记录需要提供所有必需字段：signal_type, etf_symbol, signal_strength, strategy, entry_price'
                }
            if status is None:
                status = 'pending'
        
        success = record_signal_effect(
            signal_id=signal_id,
            signal_type=signal_type,
            etf_symbol=etf_symbol,
            signal_strength=signal_strength,
            strategy=strategy,
            entry_price=entry_price,
            exit_price=exit_price,
            profit_loss=profit_loss,
            profit_loss_pct=profit_loss_pct,
            holding_days=holding_days,
            status=status,
            exit_reason=exit_reason,
            journal_extra=journal_extra,
        )
        
        return {
            'success': success,
            'message': '信号效果已记录' if success else '信号效果记录失败'
        }
    except Exception as e:
        return {
            'success': False,
            'message': f'错误: {str(e)}'
        }


def tool_get_strategy_performance(
    strategy: str,
    lookback_days: int = 60,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    trading_costs: Optional[Dict[str, Any]] = None,
    by_regime: bool = False,
) -> Dict[str, Any]:
    """OpenClaw 工具：获取策略表现（支持日期区间、交易成本、regime 分组）"""
    return get_strategy_performance(
        strategy=strategy,
        lookback_days=lookback_days,
        start_date=start_date,
        end_date=end_date,
        trading_costs=trading_costs,
        by_regime=by_regime,
    )
