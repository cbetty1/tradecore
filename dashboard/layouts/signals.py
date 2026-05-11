from dash import html
from data.price_feed import get_historical_data, get_latest_price
from signals.momentum import MomentumSignal
from signals.confidence_scorer import score_signal
import json


def layout():
    """Build and return the signals feed layout."""

    with open("config/watchlist.json") as f:
        watchlist = json.load(f)["watchlist"]

    signal_engine = MomentumSignal()
    rows = []

    for stock in watchlist:
        ticker = stock["ticker"]
        df = get_historical_data(ticker, period="1y")
        price = get_latest_price(ticker)

        if df is None or not price:
            rows.append(_signal_row(ticker, "N/A", 0, 0, "ERROR"))
            continue

        raw = signal_engine.evaluate(ticker, df)
        final = score_signal(raw, df)
        rows.append(_signal_row(ticker, final.direction,
                                final.confidence, price, final.regime))

    return html.Div([
        html.H3("Live Signal Feed", style={"color": "#888",
                "fontSize": "14px", "marginBottom": "15px"}),
        html.P("Signals are scored 0-100. Above 65 = BUY. Below 35 = SELL.",
               style={"color": "#555", "fontSize": "12px",
                      "marginBottom": "15px"}),
        html.Div(rows)
    ])


def _signal_row(ticker, direction, confidence, price, regime):
    """Build a single signal row."""

    if direction == "BUY":
        dot = "🟢"
        dir_color = "#00ff88"
    elif direction == "SELL":
        dot = "🔴"
        dir_color = "#ff4444"
    elif direction == "WATCH":
        dot = "🟡"
        dir_color = "#ffaa00"
    else:
        dot = "⚪"
        dir_color = "#888"

    # Confidence bar
    bar_fill = int(confidence * 1.5)
    bar_color = "#00ff88" if confidence >= 65 else "#ffaa00" if confidence >= 35 else "#ff4444"

    return html.Div([
        # Ticker and direction
        html.Div([
            html.Span(f"{dot} ", style={"fontSize": "16px"}),
            html.Span(ticker, style={"color": "#fff", "fontWeight": "bold",
                                     "fontSize": "15px", "marginRight": "10px"}),
            html.Span(direction, style={"color": dir_color,
                                        "fontWeight": "bold", "fontSize": "13px"}),
        ], style={"display": "flex", "alignItems": "center", "minWidth": "180px"}),

        # Confidence bar
        html.Div([
            html.Div(style={
                "width": f"{bar_fill}px",
                "height": "6px",
                "backgroundColor": bar_color,
                "borderRadius": "3px"
            }),
        ], style={
            "width": "150px",
            "height": "6px",
            "backgroundColor": "#222",
            "borderRadius": "3px",
            "margin": "0 15px"
        }),

        # Confidence %
        html.Span(f"{confidence:.0f}%", style={"color": dir_color,
                  "fontWeight": "bold", "minWidth": "45px"}),

        # Price
        html.Span(f"£{price:.2f}" if price else "N/A",
                  style={"color": "#aaa", "minWidth": "90px",
                         "textAlign": "right"}),

        # Regime
        html.Span(regime or "—", style={"color": "#555",
                  "fontSize": "11px", "marginLeft": "15px"}),

    ], style={
        "display": "flex",
        "alignItems": "center",
        "padding": "12px 15px",
        "backgroundColor": "#111",
        "borderRadius": "6px",
        "marginBottom": "6px",
        "borderLeft": f"3px solid {dir_color}"
    })