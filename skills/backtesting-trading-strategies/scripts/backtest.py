#!/usr/bin/env python3
"""
Main Backtesting Engine
Run trading strategy backtests with performance analysis.

Usage:
    python backtest.py --strategy sma_crossover --symbol BTC-USD --period 1y
    python backtest.py --strategy rsi_reversal --symbol ETH-USD --start 2023-01-01 --end 2024-01-01
"""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

import pandas as pd
import numpy as np

# Add script directory to path
sys.path.insert(0, str(Path(__file__).parent))

from strategies import get_strategy, list_strategies, Signal
from metrics import Trade, BacktestResult, calculate_all_metrics, format_results


def parse_period(period: str) -> timedelta:
    """Parse period string like '1y', '6m', '30d'."""
    unit = period[-1].lower()
    value = int(period[:-1])
    
    if unit == 'y':
        return timedelta(days=value * 365)
    elif unit == 'm':
        return timedelta(days=value * 30)
    elif unit == 'd':
        return timedelta(days=value)
    elif unit == 'w':
        return timedelta(weeks=value)
    else:
        raise ValueError(f"Unknown period unit: {unit}")


def min_bars_for_strategy(strategy_name: str) -> int:
    """Minimum number of daily bars required (lookback + buffer, floor50)."""
    strat = get_strategy(strategy_name)
    return max(50, strat.lookback + 5)


def load_data(
    symbol: str,
    start: datetime,
    end: datetime,
    data_dir: Path,
    data_source: Optional[str] = None,
    skill_root: Optional[Path] = None,
) -> pd.DataFrame:
    """Load price data from CSV or fetch if not cached.

    Provider resolution: CLI ``data_source`` > env ``BACKTEST_DATA_SOURCE`` >
    ``data.provider`` in ``config/settings.yaml`` > ``auto``. Override config path with
    ``BACKTEST_SKILL_SETTINGS``.

    For A-share ETF / 6-digit symbols with ``auto``/``china``, uses
    ``plugins/data_collection`` (aligned with openclaw-data-china-stock), not Yahoo.
    """
    from china_stock_loader import (
        try_load_cn_etf_ohlcv,
        should_try_china_first,
        is_cn_listed_numeric_symbol,
    )
    from skill_settings import effective_data_source

    root = skill_root or Path(__file__).resolve().parent.parent
    src = effective_data_source(root, cli=data_source)

    # Try to load from cache
    cache_file = data_dir / f"{symbol.replace('/', '_').replace('-', '_')}_1d.csv"

    if cache_file.exists():
        df = pd.read_csv(cache_file, parse_dates=['date'], index_col='date')
        # Remove timezone info for comparison
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
        if len(df) > 0:
            df.attrs["price_loader"] = "cache:csv"
            return df

    # Multi-source CN ETF path (AkShare / mootdx / project cache / …)
    if should_try_china_first(src, symbol):
        df_cn, cn_src = try_load_cn_etf_ohlcv(symbol, start, end)
        if df_cn is not None and len(df_cn) > 0:
            data_dir.mkdir(parents=True, exist_ok=True)
            df_cn.attrs["price_loader"] = f"china:{cn_src or 'plugins/data_collection'}"
            df_cn.to_csv(cache_file)
            return df_cn

        if src == "china" and is_cn_listed_numeric_symbol(symbol):
            print(
                f"Error: China-market data fetch failed for {symbol} "
                f"(plugins/data_collection ETF pipeline). Not using yfinance in --data-source china.",
                file=sys.stderr,
            )
            sys.exit(1)

        if (
            src == "auto"
            and is_cn_listed_numeric_symbol(symbol)
            and os.environ.get("BACKTEST_CN_FALLBACK_YFINANCE", "0").strip().lower()
            not in ("1", "true", "yes")
        ):
            print(
                f"Error: China-market data fetch failed for {symbol}. "
                "Refusing Yahoo fallback (wrong venue for CN ETFs). "
                "Fix AkShare/network cache, or set BACKTEST_CN_FALLBACK_YFINANCE=1 to force Yahoo.",
                file=sys.stderr,
            )
            sys.exit(1)

    # CoinGecko (crypto; from YAML ``data.provider: coingecko`` or CLI)
    if src == "coingecko":
        from fetch_data import fetch_coingecko

        days = max(1, (end - start).days)
        df = fetch_coingecko(symbol, days)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
        if len(df) == 0:
            print("Error: CoinGecko returned no rows in the requested date range.", file=sys.stderr)
            sys.exit(1)
        data_dir.mkdir(parents=True, exist_ok=True)
        df.attrs["price_loader"] = "coingecko"
        df.to_csv(cache_file)
        return df

    # Yahoo Finance (crypto, US symbols, or explicit yfinance / opt-in CN fallback)
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, end=end, interval='1d')
        df.columns = [c.lower() for c in df.columns]
        df.index.name = 'date'

        # Remove timezone for consistency
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        # Cache the data
        data_dir.mkdir(parents=True, exist_ok=True)
        df.attrs["price_loader"] = "yfinance"
        df.to_csv(cache_file)

        return df
    except ImportError:
        print("yfinance not installed. Install with: pip install yfinance")
        sys.exit(1)
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        sys.exit(1)


def run_backtest(
    strategy_name: str,
    data: pd.DataFrame,
    initial_capital: float = 10000,
    params: Dict[str, Any] = None,
    commission: float = 0.001,
    slippage: float = 0.0005,
) -> BacktestResult:
    """Run a backtest on historical data."""
    
    params = params or {}
    strategy = get_strategy(strategy_name)
    
    trades: List[Trade] = []
    equity = [initial_capital]
    cash = initial_capital
    position = None
    position_size = 0
    
    for i in range(strategy.lookback, len(data)):
        # Get data slice up to current bar
        slice_data = data.iloc[:i+1].copy()
        current_bar = data.iloc[i]
        current_price = current_bar['close']
        current_time = data.index[i]
        
        # Generate signals
        signal = strategy.generate_signals(slice_data, params)
        
        # Apply slippage
        buy_price = current_price * (1 + slippage)
        sell_price = current_price * (1 - slippage)
        
        # Execute trades
        if signal.entry and position is None:
            # Enter position
            position_value = cash * 0.95  # Use 95% of cash (keep some reserve)
            position_size = position_value / buy_price
            commission_cost = position_value * commission
            cash -= position_value + commission_cost
            
            position = {
                'entry_time': current_time,
                'entry_price': buy_price,
                'direction': signal.direction,
                'size': position_size,
            }
        
        elif signal.exit and position is not None:
            # Exit position
            exit_value = position_size * sell_price
            commission_cost = exit_value * commission
            cash += exit_value - commission_cost
            
            trade = Trade(
                entry_time=position['entry_time'],
                exit_time=current_time,
                entry_price=position['entry_price'],
                exit_price=sell_price,
                direction=position['direction'],
                size=position['size'],
            )
            trades.append(trade)
            position = None
            position_size = 0
        
        # Calculate equity (cash + position value)
        if position is not None:
            equity.append(cash + position_size * current_price)
        else:
            equity.append(cash)
    
    # Close any open position at end
    if position is not None:
        final_price = data.iloc[-1]['close'] * (1 - slippage)
        exit_value = position_size * final_price
        commission_cost = exit_value * commission
        cash += exit_value - commission_cost
        
        trade = Trade(
            entry_time=position['entry_time'],
            exit_time=data.index[-1],
            entry_price=position['entry_price'],
            exit_price=final_price,
            direction=position['direction'],
            size=position['size'],
        )
        trades.append(trade)
        equity[-1] = cash
    
    # Create equity curve
    equity_curve = pd.Series(equity, index=data.index[strategy.lookback-1:])
    
    # Build result
    result = BacktestResult(
        strategy=strategy_name,
        symbol=data.attrs.get('symbol', 'Unknown'),
        start_date=data.index[0],
        end_date=data.index[-1],
        initial_capital=initial_capital,
        final_capital=equity[-1],
        trades=trades,
        equity_curve=equity_curve,
        parameters=params,
    )
    
    # Calculate all metrics
    result = calculate_all_metrics(result)
    
    return result


def save_results(result: BacktestResult, output_dir: Path) -> None:
    """Save backtest results to files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    base_name = f"{result.strategy}_{result.symbol.replace('/', '_')}_{timestamp}"
    
    # Save summary
    summary_file = output_dir / f"{base_name}_summary.txt"
    with open(summary_file, 'w') as f:
        f.write(format_results(result))
    
    # Save trades to CSV
    if result.trades:
        trades_file = output_dir / f"{base_name}_trades.csv"
        trades_df = pd.DataFrame([
            {
                'entry_time': t.entry_time,
                'exit_time': t.exit_time,
                'entry_price': t.entry_price,
                'exit_price': t.exit_price,
                'direction': t.direction,
                'size': t.size,
                'pnl': t.pnl,
                'pnl_pct': t.pnl_pct,
                'duration': t.duration,
            }
            for t in result.trades
        ])
        trades_df.to_csv(trades_file, index=False)
    
    # Save equity curve
    equity_file = output_dir / f"{base_name}_equity.csv"
    result.equity_curve.to_csv(equity_file, header=['equity'])
    
    # Try to plot equity curve
    try:
        import matplotlib.pyplot as plt
        
        fig, axes = plt.subplots(2, 1, figsize=(12, 8))
        
        # Equity curve
        axes[0].plot(result.equity_curve, label='Portfolio Value', color='blue')
        axes[0].set_title(f'{result.strategy.upper()} - {result.symbol} Equity Curve')
        axes[0].set_ylabel('Portfolio Value ($)')
        axes[0].legend()
        axes[0].grid(True, alpha=0.3)
        
        # Drawdown
        rolling_max = result.equity_curve.expanding().max()
        drawdown = (result.equity_curve - rolling_max) / rolling_max * 100
        axes[1].fill_between(drawdown.index, drawdown, 0, alpha=0.5, color='red')
        axes[1].set_title('Drawdown')
        axes[1].set_ylabel('Drawdown (%)')
        axes[1].set_xlabel('Date')
        axes[1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        chart_file = output_dir / f"{base_name}_chart.png"
        plt.savefig(chart_file, dpi=100)
        plt.close()
        
        print(f"Chart saved to: {chart_file}")
    except ImportError:
        pass  # matplotlib not available
    
    print(f"Results saved to: {output_dir}")


def main():
    parser = argparse.ArgumentParser(description='Backtest trading strategies')
    parser.add_argument('--strategy', '-s', help='Strategy name')
    parser.add_argument('--symbol', help='Trading symbol (e.g., BTC-USD)')
    parser.add_argument('--period', '-p', help='Lookback period (e.g., 1y, 6m, 30d)')
    parser.add_argument('--start', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', help='End date (YYYY-MM-DD)')
    parser.add_argument(
        '--capital',
        '-c',
        type=float,
        default=None,
        help='Initial capital (default: backtest.default_capital in config/settings.yaml)',
    )
    parser.add_argument('--params', help='Strategy parameters as JSON')
    parser.add_argument(
        '--commission',
        type=float,
        default=None,
        help='Commission per trade (default: backtest.commission in settings.yaml)',
    )
    parser.add_argument(
        '--slippage',
        type=float,
        default=None,
        help='Slippage per trade (default: backtest.slippage in settings.yaml)',
    )
    parser.add_argument('--output', '-o', help='Output directory')
    parser.add_argument('--list', action='store_true', help='List available strategies')
    parser.add_argument('--quiet', '-q', action='store_true', help='Minimal output')
    parser.add_argument(
        '--data-source',
        choices=['auto', 'china', 'yfinance', 'coingecko'],
        default=None,
        help='Overrides env BACKTEST_DATA_SOURCE and YAML data.provider when set. '
        'coingecko is for crypto daily approximations.',
    )

    args = parser.parse_args()

    # List strategies
    if args.list:
        print("Available strategies:")
        for name, desc in list_strategies().items():
            print(f"  {name}: {desc}")
        return

    if not args.strategy or not args.symbol:
        parser.error('the following arguments are required: --strategy, --symbol (unless --list)')
    
    # Determine date range
    if args.start and args.end:
        start = datetime.strptime(args.start, '%Y-%m-%d')
        end = datetime.strptime(args.end, '%Y-%m-%d')
    elif args.period:
        end = datetime.now()
        start = end - parse_period(args.period)
    else:
        end = datetime.now()
        start = end - timedelta(days=365)
    
    # Parse parameters
    params = json.loads(args.params) if args.params else {}
    
    # Set up directories and execution defaults from config/settings.yaml
    skill_root = Path(__file__).resolve().parent.parent
    from skill_settings import load_skill_settings, resolve_skill_path, settings_yaml_path

    settings = load_skill_settings(skill_root)
    data_dir = resolve_skill_path(skill_root, str(settings["data"]["cache_dir"]))
    output_dir = (
        Path(args.output).resolve()
        if args.output
        else resolve_skill_path(skill_root, str(settings["reporting"]["output_dir"]))
    )

    bt = settings["backtest"]
    capital = float(args.capital if args.capital is not None else bt["default_capital"])
    commission = float(args.commission if args.commission is not None else bt["commission"])
    slippage = float(args.slippage if args.slippage is not None else bt["slippage"])

    # Load data
    if not args.quiet:
        print(f"Settings file: {settings_yaml_path(skill_root)}")
        print(f"Loading data for {args.symbol} from {start.date()} to {end.date()}...")

    data = load_data(
        args.symbol,
        start,
        end,
        data_dir,
        data_source=args.data_source,
        skill_root=skill_root,
    )
    data.attrs['symbol'] = args.symbol

    min_bars = min_bars_for_strategy(args.strategy)
    if len(data) < min_bars:
        strat = get_strategy(args.strategy)
        print(
            f"Error: Insufficient data. Got {len(data)} bars, need at least {min_bars} "
            f"for strategy {args.strategy} (lookback={strat.lookback}). "
            "Widen --period or set --start/--end.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.quiet:
        loader = data.attrs.get("price_loader", "unknown")
        print(f"Loaded {len(data)} bars (price_loader={loader})")
        print(f"Running backtest with {args.strategy} strategy...")
    
    # Run backtest
    result = run_backtest(
        strategy_name=args.strategy,
        data=data,
        initial_capital=capital,
        params=params,
        commission=commission,
        slippage=slippage,
    )
    
    # Print results
    print(format_results(result))
    
    # Save results
    save_results(result, output_dir)


if __name__ == '__main__':
    main()
