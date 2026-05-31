import json
import os
from dash import html
from risk.drawdown_guard import is_kill_switch_active, get_current_drawdown
from execution.order_manager import load_portfolio_state, get_portfolio_value
from database.queries import get_snapshots

RISK_LIMITS_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "risk_limits.json"
)


def _load_risk_limits() -> dict:
    """Load current risk limits from config — never hardcode these."""
    try:
        with open(RISK_LIMITS_FILE) as f:
            return json.load(f)
    except Exception:
        return {
            "max_drawdown_pct": 8.0,
            "max_position_pct": 15.0,
            "max_open_positions": 6,
            "min_confidence_threshold": 65.0,
            "cash_floor_gbp": 20.0,
            "daily_loss_limit_pct": 3.0,
            "correlation_limit": 0.85,
            "stop_loss_pct": 5.0,
            "take_profit_pct": 15.0,
        }


def layout():
    """Build and return the risk monitor layout."""

    state = load_portfolio_state()
    portfolio_value = get_portfolio_value(state)
    starting_capital = state["starting_capital"]

    # Load live risk limits — all values come from here, nothing hardcoded
    limits = _load_risk_limits()
    max_drawdown = limits.get("max_drawdown_pct", 8.0)
    max_positions = limits.get("max_open_positions", 6)

    kill = is_kill_switch_active(
        max_drawdown_pct=max_drawdown,
        daily_loss_pct=limits.get("daily_loss_limit_pct", 3.0),
        starting_capital=starting_capital
    )

    drawdown = get_current_drawdown(starting_capital)
    drawdown_pct_of_limit = min((drawdown / max_drawdown) * 100, 100)

    # Drawdown bar color
    if drawdown_pct_of_limit < 50:
        bar_color = "#00ff88"
    elif drawdown_pct_of_limit < 75:
        bar_color = "#ffaa00"
    else:
        bar_color = "#ff4444"

    # System status
    if kill["active"]:
        status_dot = "🔴"
        status_text = "KILL SWITCH ACTIVE"
        status_color = "#ff4444"
    else:
        status_dot = "✅"
        status_text = "SYSTEM ACTIVE"
        status_color = "#00ff88"

    # Position exposure
    cash = state["cash"]
    invested = portfolio_value - cash
    exposure_pct = (invested / portfolio_value * 100) if portfolio_value > 0 else 0
    open_positions = len(state["positions"])

    return html.Div([

        # ── Status Cards ─────────────────────────────────────────────────────
        html.Div([
            _risk_card("System Status",
                       f"{status_dot} {status_text}", status_color),
            _risk_card("Open Positions",
                       f"{open_positions} / {max_positions} max", "#fff"),
            _risk_card("Cash Exposure",
                       f"{exposure_pct:.1f}% invested", "#ffaa00"),
            _risk_card("Portfolio Value",
                       f"£{portfolio_value:,.2f}", "#fff"),
        ], style={"display": "flex", "gap": "15px",
                  "marginBottom": "25px", "flexWrap": "wrap"}),

        # ── Drawdown Monitor ─────────────────────────────────────────────────
        html.Div([
            html.H3("Drawdown Monitor", style={"color": "#888",
                    "fontSize": "14px", "marginBottom": "15px"}),
            html.Div([
                html.Div([
                    html.Span("Current Drawdown",
                              style={"color": "#888", "fontSize": "13px"}),
                    html.Span(f"{drawdown:.2f}%",
                              style={"color": bar_color, "fontWeight": "bold",
                                     "fontSize": "13px"})
                ], style={"display": "flex",
                          "justifyContent": "space-between",
                          "marginBottom": "8px"}),

                # Drawdown progress bar
                html.Div([
                    html.Div(style={
                        "width": f"{drawdown_pct_of_limit}%",
                        "height": "12px",
                        "backgroundColor": bar_color,
                        "borderRadius": "6px",
                        "transition": "width 0.3s ease"
                    })
                ], style={
                    "width": "100%",
                    "height": "12px",
                    "backgroundColor": "#222",
                    "borderRadius": "6px",
                    "marginBottom": "8px"
                }),

                html.Div([
                    html.Span("0%", style={"color": "#555", "fontSize": "11px"}),
                    html.Span(f"Kill switch at {max_drawdown}%",
                              style={"color": "#555", "fontSize": "11px"}),
                ], style={"display": "flex", "justifyContent": "space-between"})
            ])
        ], style={"backgroundColor": "#111", "borderRadius": "8px",
                  "padding": "20px", "marginBottom": "20px"}),

        # ── Risk Rules ───────────────────────────────────────────────────────
        html.Div([
            html.H3("Active Risk Rules", style={"color": "#888",
                    "fontSize": "14px", "marginBottom": "15px"}),
            _rule_row("Max drawdown limit",
                      f"{limits.get('max_drawdown_pct', 8.0)}%"),
            _rule_row("Daily loss limit",
                      f"{limits.get('daily_loss_limit_pct', 3.0)}%"),
            _rule_row("Max position size",
                      f"{limits.get('max_position_pct', 15.0)}% of portfolio"),
            _rule_row("Max open positions",
                      str(max_positions)),
            _rule_row("Stop loss per trade",
                      f"{limits.get('stop_loss_pct', 5.0)}%"),
            _rule_row("Take profit per trade",
                      f"{limits.get('take_profit_pct', 15.0)}%"),
            _rule_row("Min signal confidence",
                      f"{limits.get('min_confidence_threshold', 65.0)}%"),
            _rule_row("Correlation limit",
                      f"{limits.get('correlation_limit', 0.85)}"),
        ], style={"backgroundColor": "#111", "borderRadius": "8px",
                  "padding": "20px"}),

    ])


def _risk_card(label, value, color):
    return html.Div([
        html.P(label, style={"color": "#888", "fontSize": "12px",
                             "margin": "0 0 5px 0"}),
        html.P(value, style={"color": color, "fontSize": "18px",
                             "fontWeight": "bold", "margin": "0"})
    ], style={
        "backgroundColor": "#111",
        "borderRadius": "8px",
        "padding": "15px 20px",
        "flex": "1",
        "minWidth": "150px"
    })


def _rule_row(label, value):
    return html.Div([
        html.Span(label, style={"color": "#aaa", "fontSize": "13px"}),
        html.Span(value, style={"color": "#00ff88", "fontSize": "13px",
                                "fontWeight": "bold"})
    ], style={
        "display": "flex",
        "justifyContent": "space-between",
        "padding": "8px 0",
        "borderBottom": "1px solid #1a1a1a"
    })