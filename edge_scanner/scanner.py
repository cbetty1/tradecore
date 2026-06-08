import json
import logging
from datetime import datetime
import yfinance as yf
import pandas as pd
import ta
from database.db import get_connection

logger = logging.getLogger(__name__)

WATCHLIST_PATH = "config/watchlist_edge.json"
MIN_VOLUME_SPIKE = 2.0   # 3-day avg volume must be 2x the 20-day avg
MIN_PRICE_CHANGE = 3.0   # % price change on the day
MIN_CONFIDENCE = 60.0    # minimum score to log


def load_universe():
    with open(WATCHLIST_PATH) as f:
        return [s["ticker"] for s in json.load(f)["universe"]]


def score_ticker(ticker: str) -> dict | None:
    try:
        df = yf.download(ticker, period="60d", interval="1d", progress=False, auto_adjust=True)
        if df is None or len(df) < 25:
            return None

        close = df["Close"].squeeze()
        volume = df["Volume"].squeeze()
        high = df["High"].squeeze()
        low = df["Low"].squeeze()

        current_price = float(close.iloc[-1])
        prev_price = float(close.iloc[-2])
        price_change_pct = ((current_price - prev_price) / prev_price) * 100

        vol_3d = float(volume.iloc[-3:].mean())
        vol_20d = float(volume.iloc[-20:].mean())
        volume_spike = vol_3d / vol_20d if vol_20d > 0 else 0

        # Score: 0-100
        score = 0.0
        notes = []

        # Volume spike (40 pts)
        if volume_spike >= 3.0:
            score += 40
            notes.append(f"Volume spike {volume_spike:.1f}x")
        elif volume_spike >= 2.0:
            score += 25
            notes.append(f"Volume elevated {volume_spike:.1f}x")
        elif volume_spike >= 1.5:
            score += 10
            notes.append(f"Volume slightly elevated {volume_spike:.1f}x")
        else:
            notes.append(f"Volume normal {volume_spike:.1f}x")

        # Price momentum (40 pts)
        if price_change_pct >= 8.0:
            score += 40
            notes.append(f"Strong move +{price_change_pct:.1f}%")
        elif price_change_pct >= 5.0:
            score += 30
            notes.append(f"Good move +{price_change_pct:.1f}%")
        elif price_change_pct >= 3.0:
            score += 20
            notes.append(f"Moderate move +{price_change_pct:.1f}%")
        elif price_change_pct >= 1.0:
            score += 10
            notes.append(f"Small move +{price_change_pct:.1f}%")
        else:
            notes.append(f"No meaningful move ({price_change_pct:.1f}%)")

        # RSI not overbought (20 pts) — avoid buying into exhaustion
        rsi = float(ta.momentum.RSIIndicator(close=close, window=14).rsi().iloc[-1])
        if rsi < 60:
            score += 20
            notes.append(f"RSI healthy ({rsi:.1f})")
        elif rsi < 70:
            score += 10
            notes.append(f"RSI elevated ({rsi:.1f})")
        else:
            notes.append(f"RSI overbought ({rsi:.1f})")

        if score < MIN_CONFIDENCE:
            return None

        return {
            "ticker": ticker,
            "score": round(score, 1),
            "price": current_price,
            "price_change_pct": round(price_change_pct, 2),
            "volume_spike": round(volume_spike, 2),
            "rsi": round(rsi, 1),
            "notes": " | ".join(notes),
            "scanned_at": datetime.now().isoformat()
        }

    except Exception as e:
        logger.warning(f"EdgeScanner error on {ticker}: {e}")
        return None


def log_result(result: dict):
    with get_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO edge_scanner_results
            (ticker, score, price, price_change_pct, volume_spike, rsi, notes, scanned_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result["ticker"], result["score"], result["price"],
            result["price_change_pct"], result["volume_spike"],
            result["rsi"], result["notes"], result["scanned_at"]
        ))


def run_edge_scan():
    logger.info("=== EDGE SCANNER STARTING ===")
    universe = load_universe()
    hits = []

    for ticker in universe:
        result = score_ticker(ticker)
        if result:
            log_result(result)
            hits.append(result)

    hits.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"Edge scan complete — {len(universe)} scanned | {len(hits)} hits logged")

    if hits:
        top = hits[:5]
        for h in top:
            logger.info(f"  {h['ticker']} | Score: {h['score']} | {h['price_change_pct']}% | Vol: {h['volume_spike']}x | {h['notes']}")

    return hits
