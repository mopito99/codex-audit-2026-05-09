import sys
import os
import traceback
from sqlalchemy import text
import pandas as pd

# Add the project root to sys.path so we can import app.db
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

from app.db import get_db
from app.services.fundamentals import get_crypto_fundamentals


def _print_trades(db):
    """Print trade history summary."""
    print("--- TRADES HISTORY ---")
    query_trades = text("SELECT id, timestamp, symbol, action, price, size, margin, leverage, reason, event, entry_price, exit_price, pnl_usd, sl, tp FROM paper_trades ORDER BY timestamp ASC")
    trades = db.execute(query_trades).fetchall()

    if not trades:
        print("No trades found.")
        return

    df_trades = pd.DataFrame(trades)
    closed_trades = df_trades[df_trades['event'] == 'CLOSE']
    if closed_trades.empty:
        print("No CLOSED trades found (only OPEN entries?).")
        return

    total_pnl = closed_trades['pnl_usd'].sum()
    wins = closed_trades[closed_trades['pnl_usd'] > 0]
    losses = closed_trades[closed_trades['pnl_usd'] <= 0]
    win_rate = len(wins) / len(closed_trades) * 100 if len(closed_trades) > 0 else 0

    print(f"Total Closed Trades: {len(closed_trades)}")
    print(f"Total PnL: ${total_pnl:.2f}")
    print(f"Win Rate: {win_rate:.1f}% ({len(wins)} W / {len(losses)} L)")
    print(f"Best Win: ${closed_trades['pnl_usd'].max():.2f}")
    print(f"Worst Loss: ${closed_trades['pnl_usd'].min():.2f}")

    print("\nLast 10 Closed Trades:")
    for _, t in closed_trades.tail(10).iterrows():
        print(f"{t['timestamp']} | {t['symbol']} | {t['action']} | PnL: ${t['pnl_usd']:.2f} | Entry: {t['entry_price']} | Exit: {t['exit_price']}")


def _print_equity(db):
    """Print equity status."""
    print("\n--- EQUITY STATUS ---")
    query_equity = text("SELECT symbol, balance, peak, updated_at FROM paper_equity")
    equity = db.execute(query_equity).fetchall()
    if equity:
        for row in equity:
            print(f"Symbol: {row.symbol} | Balance: ${row.balance:.2f} | Peak: ${row.peak:.2f}")
    else:
        print("No equity records found.")


def _print_positions(db):
    """Print open positions."""
    print("\n--- OPEN POSITIONS ---")
    query_pos = text("SELECT symbol, side, entry_price, notional_usd, margin_usd, leverage, qty, sl, tp, open_time FROM paper_positions")
    positions = db.execute(query_pos).fetchall()
    if positions:
        for p in positions:
            print(f"{p.symbol} | {p.side} | Entry: {p.entry_price} | Size: ${p.notional_usd:.2f} | PnL: (Unrealized)")
    else:
        print("No open positions.")


def _print_news(db):
    """Print recent news."""
    print("\n--- RECENT NEWS ---")
    try:
        query_news = text("SELECT timestamp, symbol, title, sentiment FROM news ORDER BY timestamp DESC LIMIT 5")
        news_items = db.execute(query_news).fetchall()
        if news_items:
            for n in news_items:
                title = n.title if len(n.title) < 60 else n.title[:57] + "..."
                print(f"{n.timestamp} | {n.symbol} | {title} | Sentiment: {n.sentiment}")
        else:
            print("No news found.")
    except Exception as news_error:
        print(f"Could not fetch news: {news_error}")


def _print_fundamentals():
    """Print crypto fundamentals from Investing.com."""
    print("\n--- CRYPTO FUNDAMENTALS ---")
    fundamentals = get_crypto_fundamentals()

    if fundamentals['type'] == 'today':
        print(f"Events Today ({fundamentals['date']}) [Impact {fundamentals['impact']}/3]:")
        for e in fundamentals['events']:
            print(f"{e['time']} | {e['event']}")
    elif fundamentals['type'] == 'upcoming':
        print(f"UPCOMING | {fundamentals['date']} {fundamentals['time']} | {fundamentals['event']}")
    else:
        print(fundamentals.get('message', 'No events found'))


def analyze():
    db = get_db()
    try:
        _print_trades(db)
        _print_equity(db)
        _print_positions(db)
        _print_news(db)
        _print_fundamentals()
    except Exception as e:
        print(f"Error analyzing: {e}")
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    analyze()
