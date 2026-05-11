from dash import html, dcc, callback, Output, Input, State
from execution.order_manager import load_portfolio_state, get_portfolio_value
from database.queries import get_snapshots

WITHDRAWAL_TARGET = 1000.0


def layout():
    """Build and return the wallet management layout."""

    state = load_portfolio_state()
    portfolio_value = get_portfolio_value(state)
    starting_capital = state["starting_capital"]
    cash = state["cash"]

    total_pnl = portfolio_value - starting_capital
    locked_profit = max(total_pnl * 0.5, 0)
    withdrawable = max(total_pnl * 0.5, 0)

    # Withdrawal target progress
    target_progress = min((withdrawable / WITHDRAWAL_TARGET) * 100, 100)
    progress_color = "#00ff88" if target_progress >= 100 else "#ffaa00"

    pnl_color = "#00ff88" if total_pnl >= 0 else "#ff4444"
    pnl_arrow = "▲" if total_pnl >= 0 else "▼"

    # Monthly P&L from snapshots
    snapshots = get_snapshots(30)
    if len(snapshots) >= 2:
        month_start = snapshots[-1]["total_value"]
        month_pnl = portfolio_value - month_start
    else:
        month_pnl = 0.0

    month_color = "#00ff88" if month_pnl >= 0 else "#ff4444"

    return html.Div([

        # ── Your Money At A Glance ────────────────────────────────────────────
        html.Div([
            html.H3("Your Money At A Glance",
                    style={"color": "#888", "fontSize": "14px",
                           "marginBottom": "20px"}),

            _money_row("Started with", f"£{starting_capital:,.2f}", "#888"),
            _money_row("Portfolio now", f"£{portfolio_value:,.2f}", "#fff"),
            _money_row("Total earned",
                       f"{pnl_arrow} £{abs(total_pnl):,.2f}", pnl_color),
            html.Hr(style={"borderColor": "#222", "margin": "10px 0"}),
            _money_row("Safe to withdraw",
                       f"£{withdrawable:,.2f}", "#00ff88"),
            _money_row("Locked (50% protected)",
                       f"£{locked_profit:,.2f}", "#ffaa00"),
            _money_row("Starting capital",
                       f"£{starting_capital:,.2f} 🔒", "#888"),

        ], style={"backgroundColor": "#111", "borderRadius": "8px",
                  "padding": "20px", "marginBottom": "20px"}),

        # ── Performance ───────────────────────────────────────────────────────
        html.Div([
            html.H3("Performance",
                    style={"color": "#888", "fontSize": "14px",
                           "marginBottom": "15px"}),
            _money_row("This month",
                       f"£{month_pnl:+,.2f}", month_color),
            _money_row("Cash available",
                       f"£{cash:,.2f}", "#00aaff"),
            _money_row("Invested",
                       f"£{portfolio_value - cash:,.2f}", "#ffaa00"),
        ], style={"backgroundColor": "#111", "borderRadius": "8px",
                  "padding": "20px", "marginBottom": "20px"}),

        # ── Withdrawal Target ─────────────────────────────────────────────────
        html.Div([
            html.H3("Withdrawal Target",
                    style={"color": "#888", "fontSize": "14px",
                           "marginBottom": "15px"}),

            html.Div([
                html.Span("Progress to £1,000 target",
                          style={"color": "#aaa", "fontSize": "13px"}),
                html.Span(f"£{withdrawable:,.2f} / £{WITHDRAWAL_TARGET:,.2f}",
                          style={"color": progress_color,
                                 "fontSize": "13px", "fontWeight": "bold"})
            ], style={"display": "flex", "justifyContent": "space-between",
                      "marginBottom": "10px"}),

            # Progress bar
            html.Div([
                html.Div(style={
                    "width": f"{target_progress}%",
                    "height": "14px",
                    "backgroundColor": progress_color,
                    "borderRadius": "7px",
                    "transition": "width 0.5s ease"
                })
            ], style={
                "width": "100%",
                "height": "14px",
                "backgroundColor": "#222",
                "borderRadius": "7px",
                "marginBottom": "10px"
            }),

            html.P(
                "🎯 Target reached! Ready to withdraw." if target_progress >= 100
                else f"{target_progress:.1f}% of withdrawal target reached",
                style={"color": progress_color, "fontSize": "12px", "margin": "0"}
            )

        ], style={"backgroundColor": "#111", "borderRadius": "8px",
                  "padding": "20px"}),
    ])


def _money_row(label, value, color):
    return html.Div([
        html.Span(label, style={"color": "#aaa", "fontSize": "14px"}),
        html.Span(value, style={"color": color, "fontSize": "14px",
                                "fontWeight": "bold"})
    ], style={
        "display": "flex",
        "justifyContent": "space-between",
        "padding": "8px 0",
        "borderBottom": "1px solid #1a1a1a"
    })