import logging
import os
import sqlite3
from datetime import datetime, timedelta
import requests

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "tradecore.db")
REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "paper_weekly_report.pdf")

# Sector map — used to cluster tickers by sector for analysis
SECTOR_MAP = {
    # Technology
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "AMD": "Technology", "INTC": "Technology", "QCOM": "Technology",
    "AVGO": "Technology", "TXN": "Technology", "MU": "Technology",
    "AMAT": "Technology", "LRCX": "Technology", "KLAC": "Technology",
    "ASML": "Technology", "TSM": "Technology", "ORCL": "Technology",
    "SAP": "Technology", "CRM": "Technology", "NOW": "Technology",
    "ADBE": "Technology", "INTU": "Technology", "SNOW": "Technology",
    "PLTR": "Technology", "UBER": "Technology", "LYFT": "Technology",
    "IBM": "Technology", "HPQ": "Technology", "DELL": "Technology",
    "ACN": "Technology", "CTSH": "Technology",
    # Communication
    "META": "Communication", "GOOGL": "Communication", "GOOG": "Communication",
    "NFLX": "Communication", "DIS": "Communication", "CMCSA": "Communication",
    "T": "Communication", "VZ": "Communication", "TMUS": "Communication",
    "SNAP": "Communication", "PINS": "Communication", "SPOT": "Communication",
    # Consumer
    "AMZN": "Consumer", "TSLA": "Consumer", "NKE": "Consumer",
    "MCD": "Consumer", "SBUX": "Consumer", "HD": "Consumer",
    "LOW": "Consumer", "TGT": "Consumer", "WMT": "Consumer",
    "COST": "Consumer", "TJX": "Consumer", "BKNG": "Consumer",
    "ABNB": "Consumer", "EBAY": "Consumer",
    # Financials
    "JPM": "Financials", "BAC": "Financials", "WFC": "Financials",
    "GS": "Financials", "MS": "Financials", "BLK": "Financials",
    "V": "Financials", "MA": "Financials", "AXP": "Financials",
    "PYPL": "Financials", "COF": "Financials", "USB": "Financials",
    "PNC": "Financials", "SCHW": "Financials", "ICE": "Financials",
    # Healthcare
    "JNJ": "Healthcare", "PFE": "Healthcare", "MRK": "Healthcare",
    "ABBV": "Healthcare", "LLY": "Healthcare", "BMY": "Healthcare",
    "AMGN": "Healthcare", "GILD": "Healthcare", "BIIB": "Healthcare",
    "ISRG": "Healthcare", "DHR": "Healthcare", "TMO": "Healthcare",
    "ABT": "Healthcare", "MDT": "Healthcare", "SYK": "Healthcare",
    # Energy
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy",
    "SLB": "Energy", "EOG": "Energy", "PXD": "Energy",
    "OXY": "Energy", "MPC": "Energy", "PSX": "Energy",
    # Industrials
    "BA": "Industrials", "CAT": "Industrials", "GE": "Industrials",
    "HON": "Industrials", "MMM": "Industrials", "UPS": "Industrials",
    "FDX": "Industrials", "LMT": "Industrials", "RTX": "Industrials",
    "DE": "Industrials", "EMR": "Industrials",
}


def _get_sector(ticker: str) -> str:
    """Return sector for a ticker, or 'Other' if unknown."""
    return SECTOR_MAP.get(ticker.upper().replace(".L", "").replace(".AS", ""), "Other")


def run_paper_analysis() -> dict:
    """
    Query the DB and compute all paper scanner stats for the week.
    Returns a dict consumed by generate_paper_report_pdf() and
    send_paper_analysis_telegram().
    """
    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday())  # Monday

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row

        # ── 1. Signal type breakdown ───────────────────────────────────────
        signal_counts = conn.execute("""
            SELECT
                REPLACE(REPLACE(REPLACE(s.signal_type, 'PAPER_', ''), '_PAPER', ''), 'PAPER', '') as clean_type,
                COUNT(*) as count,
                AVG(s.confidence) as avg_confidence
            FROM signals s
            WHERE date(s.created_at) >= ?
            AND s.signal_type LIKE '%PAPER%'
            GROUP BY clean_type
            ORDER BY count DESC
        """, (str(week_start),)).fetchall()

        # ── 2. Paper trades this week ──────────────────────────────────────
        all_paper_trades = conn.execute("""
            SELECT t.ticker, t.pnl, t.opened_at, t.closed_at, t.price,
                   t.quantity, t.total_value, t.status,
                   s.signal_type, s.confidence, s.regime
            FROM trades t
            LEFT JOIN signals s ON t.signal_id = s.id
            WHERE t.paper = 1
            AND (date(t.opened_at) >= ? OR date(t.closed_at) >= ?)
        """, (str(week_start), str(week_start))).fetchall()

        closed_trades = [r for r in all_paper_trades if r["status"] == "CLOSED" and r["pnl"] is not None]
        open_trades = [r for r in all_paper_trades if r["status"] == "OPEN"]

        # ── 3. Win/loss stats ─────────────────────────────────────────────
        wins = [r for r in closed_trades if r["pnl"] > 0]
        losses = [r for r in closed_trades if r["pnl"] <= 0]
        total_closed = len(closed_trades)
        win_rate = (len(wins) / total_closed * 100) if total_closed > 0 else 0.0
        avg_win = sum(r["pnl"] for r in wins) / len(wins) if wins else 0.0
        avg_loss = sum(r["pnl"] for r in losses) / len(losses) if losses else 0.0
        total_pnl_closed = sum(r["pnl"] for r in closed_trades)

        # ── 4. Signal type performance ────────────────────────────────────
        signal_perf = {}
        for r in closed_trades:
            raw_type = (r["signal_type"] or "UNKNOWN")
            clean = raw_type.replace("PAPER_", "").replace("_PAPER", "").replace("PAPER", "")
            if clean not in signal_perf:
                signal_perf[clean] = {"wins": 0, "losses": 0, "total_pnl": 0.0, "trades": 0}
            signal_perf[clean]["trades"] += 1
            signal_perf[clean]["total_pnl"] += r["pnl"]
            if r["pnl"] > 0:
                signal_perf[clean]["wins"] += 1
            else:
                signal_perf[clean]["losses"] += 1

        for k in signal_perf:
            t = signal_perf[k]["trades"]
            signal_perf[k]["win_rate"] = (signal_perf[k]["wins"] / t * 100) if t > 0 else 0.0

        # ── 5. Confidence score vs performance ────────────────────────────
        # Bucket into bands: 65-74, 75-84, 85-94, 95+
        confidence_bands = {
            "65-74": {"trades": 0, "wins": 0, "total_pnl": 0.0},
            "75-84": {"trades": 0, "wins": 0, "total_pnl": 0.0},
            "85-94": {"trades": 0, "wins": 0, "total_pnl": 0.0},
            "95+":   {"trades": 0, "wins": 0, "total_pnl": 0.0},
        }
        for r in closed_trades:
            conf = r["confidence"] or 0
            if conf >= 95:
                band = "95+"
            elif conf >= 85:
                band = "85-94"
            elif conf >= 75:
                band = "75-84"
            else:
                band = "65-74"
            confidence_bands[band]["trades"] += 1
            confidence_bands[band]["total_pnl"] += r["pnl"]
            if r["pnl"] > 0:
                confidence_bands[band]["wins"] += 1

        for band in confidence_bands:
            t = confidence_bands[band]["trades"]
            confidence_bands[band]["win_rate"] = (confidence_bands[band]["wins"] / t * 100) if t > 0 else 0.0

        # ── 6. Top 5 and bottom 5 closed trades ───────────────────────────
        sorted_closed = sorted(closed_trades, key=lambda r: r["pnl"] or 0, reverse=True)
        top_5 = sorted_closed[:5]
        bottom_5 = sorted_closed[-5:] if len(sorted_closed) >= 5 else sorted_closed[::-1]

        # Hold time for closed trades
        def hold_days(r):
            try:
                opened = datetime.fromisoformat(r["opened_at"])
                closed = datetime.fromisoformat(r["closed_at"])
                return (closed - opened).days
            except Exception:
                return 0

        # ── 7. Sector clustering ──────────────────────────────────────────
        sector_counts = {}
        sector_pnl = {}
        for r in all_paper_trades:
            sector = _get_sector(r["ticker"])
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            if r["pnl"]:
                sector_pnl[sector] = sector_pnl.get(sector, 0.0) + r["pnl"]

        # ── 8. Scan efficiency ────────────────────────────────────────────
        total_signals = conn.execute("""
            SELECT COUNT(*) as count FROM signals
            WHERE date(created_at) >= ?
            AND signal_type LIKE '%PAPER%'
        """, (str(week_start),)).fetchone()["count"]

        unique_tickers_scanned = conn.execute("""
            SELECT COUNT(DISTINCT ticker) as count FROM signals
            WHERE date(created_at) >= ?
            AND signal_type LIKE '%PAPER%'
        """, (str(week_start),)).fetchone()["count"]

        # ── 9. Market regime breakdown ────────────────────────────────────
        regime_counts = conn.execute("""
            SELECT regime, COUNT(*) as count
            FROM signals
            WHERE date(created_at) >= ?
            AND signal_type LIKE '%PAPER%'
            AND regime IS NOT NULL
            GROUP BY regime
        """, (str(week_start),)).fetchall()

        conn.close()

        # Week number since paper launch
        paper_launch = datetime.strptime("2026-05-19", "%Y-%m-%d").date()
        week_number = max(1, ((today - paper_launch).days // 7) + 1)

        return {
            "week_start": str(week_start),
            "week_end": str(today),
            "week_number": week_number,
            "signal_counts": [dict(r) for r in signal_counts],
            "total_signals": total_signals,
            "unique_tickers_scanned": unique_tickers_scanned,
            "total_closed": total_closed,
            "total_open": len(open_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "total_pnl_closed": total_pnl_closed,
            "signal_perf": signal_perf,
            "confidence_bands": confidence_bands,
            "top_5": [dict(r) for r in top_5],
            "bottom_5": [dict(r) for r in bottom_5],
            "sector_counts": sector_counts,
            "sector_pnl": sector_pnl,
            "regime_counts": [dict(r) for r in regime_counts],
            "hold_days_fn": hold_days,
        }

    except Exception as e:
        logger.error(f"Paper analysis query failed: {e}")
        return {}


def generate_paper_report_pdf(data: dict) -> str | None:
    """
    Generate a PDF report from the analysis data.
    Returns the path to the generated PDF, or None on failure.
    """
    if not data:
        return None

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                        Table, TableStyle, HRFlowable)

        doc = SimpleDocTemplate(
            REPORT_PATH,
            pagesize=A4,
            rightMargin=2*cm, leftMargin=2*cm,
            topMargin=2*cm, bottomMargin=2*cm
        )

        styles = getSampleStyleSheet()

        # Custom styles
        title_style = ParagraphStyle(
            "TCTitle",
            parent=styles["Title"],
            fontSize=18,
            textColor=colors.HexColor("#00FF88"),
            spaceAfter=4,
        )
        heading_style = ParagraphStyle(
            "TCHeading",
            parent=styles["Heading2"],
            fontSize=12,
            textColor=colors.HexColor("#00FF88"),
            spaceBefore=12,
            spaceAfter=4,
        )
        normal = styles["Normal"]
        small = ParagraphStyle("Small", parent=normal, fontSize=8)

        def hr():
            return HRFlowable(width="100%", thickness=0.5,
                              color=colors.HexColor("#333333"), spaceAfter=6)

        def tbl(data_rows, col_widths=None):
            t = Table(data_rows, colWidths=col_widths)
            t.setStyle(TableStyle([
                ("BACKGROUND",   (0, 0), (-1, 0),  colors.HexColor("#111111")),
                ("TEXTCOLOR",    (0, 0), (-1, 0),  colors.HexColor("#00FF88")),
                ("FONTNAME",     (0, 0), (-1, 0),  "Helvetica-Bold"),
                ("FONTSIZE",     (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.HexColor("#1a1a1a"), colors.HexColor("#222222")]),
                ("TEXTCOLOR",    (0, 1), (-1, -1), colors.white),
                ("GRID",         (0, 0), (-1, -1), 0.25, colors.HexColor("#333333")),
                ("LEFTPADDING",  (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING",   (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
            ]))
            return t

        story = []

        # ── Header ────────────────────────────────────────────────────────
        story.append(Paragraph("TradeCore — Weekly Paper Analysis", title_style))
        story.append(Paragraph(
            f"Week {data['week_number']} | "
            f"{data['week_start']} to {data['week_end']} | "
            f"Generated {datetime.now().strftime('%d %b %Y %H:%M')}",
            small
        ))
        story.append(hr())

        # ── 1. Overview ───────────────────────────────────────────────────
        story.append(Paragraph("1. Overview", heading_style))
        overview_rows = [
            ["Metric", "Value"],
            ["Unique tickers scanned", str(data["unique_tickers_scanned"])],
            ["Total signals generated", str(data["total_signals"])],
            ["Paper trades opened this week", str(data["total_open"] + data["total_closed"])],
            ["Trades closed this week", str(data["total_closed"])],
            ["Currently open positions", str(data["total_open"])],
            ["Win rate (closed trades)", f"{data['win_rate']:.1f}%"],
            ["Avg winning trade", f"+£{data['avg_win']:.2f}"],
            ["Avg losing trade", f"-£{abs(data['avg_loss']):.2f}"],
            ["Total realised P&L", f"£{data['total_pnl_closed']:+.2f}"],
        ]
        story.append(tbl(overview_rows, col_widths=[10*cm, 6*cm]))
        story.append(Spacer(1, 8))

        # ── 2. Signal Type Breakdown ──────────────────────────────────────
        story.append(Paragraph("2. Signal Type Performance", heading_style))
        sig_rows = [["Signal Type", "Trades", "Wins", "Losses", "Win Rate", "Total P&L"]]
        for sig_type, perf in data["signal_perf"].items():
            pnl_str = f"£{perf['total_pnl']:+.2f}"
            sig_rows.append([
                sig_type,
                str(perf["trades"]),
                str(perf["wins"]),
                str(perf["losses"]),
                f"{perf['win_rate']:.0f}%",
                pnl_str,
            ])
        if len(sig_rows) == 1:
            sig_rows.append(["No closed trades yet", "-", "-", "-", "-", "-"])
        story.append(tbl(sig_rows, col_widths=[5*cm, 2*cm, 2*cm, 2*cm, 2.5*cm, 3*cm]))
        story.append(Spacer(1, 8))

        # ── 3. Confidence Score vs Performance ───────────────────────────
        story.append(Paragraph("3. Confidence Score vs Performance", heading_style))
        story.append(Paragraph(
            "Does higher confidence actually lead to better trades?", small
        ))
        story.append(Spacer(1, 4))
        conf_rows = [["Confidence Band", "Trades", "Win Rate", "Total P&L"]]
        for band, stats in data["confidence_bands"].items():
            conf_rows.append([
                band + "%",
                str(stats["trades"]),
                f"{stats['win_rate']:.0f}%" if stats["trades"] > 0 else "-",
                f"£{stats['total_pnl']:+.2f}" if stats["trades"] > 0 else "-",
            ])
        story.append(tbl(conf_rows, col_widths=[5*cm, 3*cm, 3*cm, 5*cm]))
        story.append(Spacer(1, 8))

        # ── 4. Top 5 Trades ───────────────────────────────────────────────
        story.append(Paragraph("4. Top 5 Closed Trades", heading_style))
        top_rows = [["Ticker", "P&L", "Signal", "Confidence", "Hold (days)"]]
        hold_fn = data.get("hold_days_fn", lambda r: "-")
        for r in data["top_5"]:
            sig = (r.get("signal_type") or "").replace("PAPER_", "")
            top_rows.append([
                r["ticker"],
                f"£{r['pnl']:+.2f}",
                sig,
                f"{r['confidence']:.0f}%" if r.get("confidence") else "-",
                str(hold_fn(r)),
            ])
        if len(top_rows) == 1:
            top_rows.append(["No closed trades yet", "-", "-", "-", "-"])
        story.append(tbl(top_rows, col_widths=[3*cm, 3*cm, 5*cm, 3*cm, 2.5*cm]))
        story.append(Spacer(1, 8))

        # ── 5. Bottom 5 Trades ────────────────────────────────────────────
        story.append(Paragraph("5. Bottom 5 Closed Trades", heading_style))
        bot_rows = [["Ticker", "P&L", "Signal", "Confidence", "Hold (days)"]]
        for r in data["bottom_5"]:
            sig = (r.get("signal_type") or "").replace("PAPER_", "")
            bot_rows.append([
                r["ticker"],
                f"£{r['pnl']:+.2f}",
                sig,
                f"{r['confidence']:.0f}%" if r.get("confidence") else "-",
                str(hold_fn(r)),
            ])
        if len(bot_rows) == 1:
            bot_rows.append(["No closed trades yet", "-", "-", "-", "-"])
        story.append(tbl(bot_rows, col_widths=[3*cm, 3*cm, 5*cm, 3*cm, 2.5*cm]))
        story.append(Spacer(1, 8))

        # ── 6. Sector Clustering ──────────────────────────────────────────
        story.append(Paragraph("6. Sector Clustering", heading_style))
        story.append(Paragraph(
            "Which sectors are generating the most paper signals?", small
        ))
        story.append(Spacer(1, 4))
        sector_rows = [["Sector", "Trade Count", "Realised P&L"]]
        for sector, count in sorted(data["sector_counts"].items(),
                                    key=lambda x: x[1], reverse=True):
            pnl = data["sector_pnl"].get(sector, 0.0)
            sector_rows.append([
                sector,
                str(count),
                f"£{pnl:+.2f}" if pnl != 0 else "-",
            ])
        story.append(tbl(sector_rows, col_widths=[6*cm, 4*cm, 6*cm]))
        story.append(Spacer(1, 8))

        # ── 7. Market Regime ─────────────────────────────────────────────
        story.append(Paragraph("7. Market Regime During Scan Week", heading_style))
        regime_rows = [["Regime", "Signal Count"]]
        for r in data["regime_counts"]:
            regime_rows.append([r["regime"] or "Unknown", str(r["count"])])
        if len(regime_rows) == 1:
            regime_rows.append(["No data", "-"])
        story.append(tbl(regime_rows, col_widths=[8*cm, 8*cm]))
        story.append(Spacer(1, 8))

        # ── Footer ────────────────────────────────────────────────────────
        story.append(hr())
        story.append(Paragraph(
            "TradeCore Paper Scanner — For strategy review only. "
            "No real capital at risk in this report.",
            small
        ))

        doc.build(story)
        logger.info(f"Paper analysis PDF generated: {REPORT_PATH}")
        return REPORT_PATH

    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        return None


def send_paper_analysis_telegram(data: dict, pdf_path: str | None) -> bool:
    """
    Send the headline summary message + PDF file to Telegram.
    """
    from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

    base_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

    # ── Headline Telegram message ─────────────────────────────────────────
    if not data:
        requests.post(f"{base_url}/sendMessage", json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": "📊 <b>PAPER ANALYSIS</b>\n\nNo data available this week.",
            "parse_mode": "HTML"
        }, timeout=10)
        return False

    # Find best performing signal type
    best_signal = "-"
    best_signal_wr = 0.0
    for sig_type, perf in data["signal_perf"].items():
        if perf["win_rate"] > best_signal_wr and perf["trades"] >= 2:
            best_signal = sig_type
            best_signal_wr = perf["win_rate"]

    # Find best confidence band
    best_band = "-"
    best_band_wr = 0.0
    for band, stats in data["confidence_bands"].items():
        if stats["trades"] > 0 and stats["win_rate"] > best_band_wr:
            best_band = band + "%"
            best_band_wr = stats["win_rate"]

    # Top sector by trade count
    top_sector = "-"
    if data["sector_counts"]:
        top_sector = max(data["sector_counts"], key=data["sector_counts"].get)

    message = (
        f"📊 <b>PAPER ANALYSIS — WEEK {data['week_number']}</b>\n"
        f"\n"
        f"<b>Trades closed:</b> {data['total_closed']} "
        f"({data['wins']}W / {data['losses']}L — {data['win_rate']:.0f}% win rate)\n"
        f"<b>Realised P&L:</b> £{data['total_pnl_closed']:+.2f}\n"
        f"\n"
        f"<b>Best signal type:</b> {best_signal} ({best_signal_wr:.0f}% win rate)\n"
        f"<b>Best confidence band:</b> {best_band} ({best_band_wr:.0f}% win rate)\n"
        f"<b>Most active sector:</b> {top_sector}\n"
        f"\n"
        f"<i>Full breakdown in the attached PDF 👇</i>\n"
        f"\n"
        f"📋 TradeCore Paper Scanner — Week {data['week_number']}"
    )

    try:
        requests.post(f"{base_url}/sendMessage", json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        logger.error(f"Failed to send analysis message: {e}")

    # ── Send PDF as file attachment ────────────────────────────────────────
    if pdf_path and os.path.exists(pdf_path):
        try:
            with open(pdf_path, "rb") as f:
                requests.post(
                    f"{base_url}/sendDocument",
                    data={"chat_id": TELEGRAM_CHAT_ID,
                          "caption": f"TradeCore Paper Analysis — Week {data['week_number']}"},
                    files={"document": (os.path.basename(pdf_path), f, "application/pdf")},
                    timeout=30
                )
            logger.info("Paper analysis PDF sent to Telegram")
            return True
        except Exception as e:
            logger.error(f"Failed to send PDF to Telegram: {e}")
            return False

    return True


def run_weekly_paper_analysis():
    """
    Main entry point — called by scheduler at Friday 17:45.
    Runs analysis, generates PDF, sends both to Telegram.
    """
    logger.info("=== WEEKLY PAPER ANALYSIS STARTING ===")
    try:
        data = run_paper_analysis()
        pdf_path = generate_paper_report_pdf(data)
        send_paper_analysis_telegram(data, pdf_path)
        logger.info("=== WEEKLY PAPER ANALYSIS COMPLETE ===")
    except Exception as e:
        logger.error(f"Weekly paper analysis failed: {e}")
        # Fail silently — don't crash the scheduler