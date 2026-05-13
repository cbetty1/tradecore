from dash import html, dcc, callback, Output, Input, State, no_update
import json
import os

RISK_LIMITS_FILE = os.path.join(
    os.path.dirname(__file__), "..", "config", "risk_limits.json"
)


def _load_risk_limits() -> dict:
    """Load current risk limits from config file."""
    try:
        with open(RISK_LIMITS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {
            "max_drawdown_pct": 8.0,
            "max_position_pct": 15.0,
            "max_open_positions": 8,
            "min_confidence_threshold": 65.0,
            "cash_floor_gbp": 20.0,
            "daily_loss_limit_pct": 3.0,
            "correlation_limit": 0.85,
            "stop_loss_pct": 5.0,
            "take_profit_pct": 15.0,
            "paper_trading_mode": True,
            "cash_deployment_threshold_pct": 40.0,
            "cash_deployment_min_confidence": 80.0,
        }


def layout():
    """Build and return the settings control panel layout."""
    from execution.order_manager import load_portfolio_state, get_portfolio_value
    from risk.drawdown_guard import is_kill_switch_active

    limits = _load_risk_limits()
    state = load_portfolio_state()
    portfolio_value = get_portfolio_value(state)
    cash = state["cash"]
    open_positions = len(state["positions"])
    is_paper = limits.get("paper_trading_mode", True)

    kill = is_kill_switch_active(
        max_drawdown_pct=limits.get("max_drawdown_pct", 8.0),
        daily_loss_pct=limits.get("daily_loss_limit_pct", 3.0),
        starting_capital=state["starting_capital"],
    )

    # ── Mode badge ────────────────────────────────────────────────────────
    if is_paper:
        mode_text = "📋 PAPER MODE"
        mode_color = "#ffaa00"
    else:
        mode_text = "🟢 LIVE TRADING"
        mode_color = "#00ff88"

    kill_text = "🔴 HALTED" if kill["active"] else "✅ ACTIVE"
    kill_color = "#ff4444" if kill["active"] else "#00ff88"

    return html.Div([

        # ── Live Status Bar ───────────────────────────────────────────────
        html.Div([
            _status_card("Mode", mode_text, mode_color),
            _status_card("Portfolio", f"£{portfolio_value:,.2f}", "#fff"),
            _status_card("Positions",
                         f"{open_positions} / {limits.get('max_open_positions', 8)}",
                         "#fff"),
            _status_card("Cash", f"£{cash:,.2f}", "#00aaff"),
            _status_card("Kill Switch", kill_text, kill_color),
        ], style={
            "display": "flex", "gap": "12px", "marginBottom": "25px",
            "flexWrap": "wrap",
        }),

        # ── Risk Controls ─────────────────────────────────────────────────
        html.Div([
            html.H3("Risk Controls", style=_section_title_style()),

            _setting_row(
                "max_open_positions",
                "Max Open Positions",
                "The most trades you can have running at the same time. "
                "Keep this low when your portfolio is small to avoid spreading "
                "your money too thin.",
                limits.get("max_open_positions", 8),
                step=1, min_val=1, max_val=20, unit="",
            ),
            _setting_row(
                "max_position_pct",
                "Max Position Size",
                "The biggest chunk of your portfolio any single trade can use. "
                "15% means no single stock can ever be more than 15% of your "
                "total money.",
                limits.get("max_position_pct", 15.0),
                step=1, min_val=1, max_val=50, unit="%",
            ),
            _setting_row(
                "stop_loss_pct",
                "Stop Loss (Trailing)",
                "How far a stock can drop from its highest point before the "
                "system sells it automatically. This follows the price upward "
                "so it locks in profits as the stock rises.",
                limits.get("stop_loss_pct", 5.0),
                step=0.5, min_val=1, max_val=20, unit="%",
            ),
            _setting_row(
                "take_profit_pct",
                "Take Profit",
                "The system sells automatically when a stock hits this much "
                "profit from your entry price. Set this to the gain you'd be "
                "happy to walk away with.",
                limits.get("take_profit_pct", 15.0),
                step=1, min_val=2, max_val=50, unit="%",
            ),
            _setting_row(
                "max_drawdown_pct",
                "Kill Switch — Max Drawdown",
                "If your total portfolio drops by this much from its peak, "
                "ALL trading stops immediately. This is your emergency brake "
                "— it protects you from a market crash.",
                limits.get("max_drawdown_pct", 8.0),
                step=0.5, min_val=2, max_val=25, unit="%",
            ),
            _setting_row(
                "daily_loss_limit_pct",
                "Daily Loss Limit",
                "If you lose this much in a single day, the system pauses "
                "until tomorrow. Prevents one bad day from wiping out a "
                "week of gains.",
                limits.get("daily_loss_limit_pct", 3.0),
                step=0.5, min_val=1, max_val=10, unit="%",
            ),
            _setting_row(
                "correlation_limit",
                "Correlation Limit",
                "Stops you from holding stocks that move together too closely. "
                "0.85 means if two stocks are more than 85% correlated, the "
                "system won't buy both. Keeps your portfolio diversified.",
                limits.get("correlation_limit", 0.85),
                step=0.05, min_val=0.5, max_val=1.0, unit="",
            ),

        ], style=_section_style()),

        # ── Signal Settings ───────────────────────────────────────────────
        html.Div([
            html.H3("Signal Settings", style=_section_title_style()),

            _setting_row(
                "min_confidence_threshold",
                "Min Confidence to Buy",
                "The system only buys when the signal score is above this "
                "number. Higher = fewer but stronger trades. Lower = more "
                "trades but some will be weaker.",
                limits.get("min_confidence_threshold", 65.0),
                step=5, min_val=30, max_val=95, unit="%",
            ),
            _setting_row(
                "cash_deployment_threshold_pct",
                "Cash Deployment Threshold",
                "If this much of your money is sitting as unused cash, the "
                "system loosens the correlation rules to put it to work. "
                "Prevents your money sitting idle too long.",
                limits.get("cash_deployment_threshold_pct", 40.0),
                step=5, min_val=20, max_val=80, unit="%",
            ),
            _setting_row(
                "cash_deployment_min_confidence",
                "Cash Deploy Min Confidence",
                "When the cash override kicks in, this is the minimum signal "
                "strength required. Set this high so the system only deploys "
                "idle cash on strong signals.",
                limits.get("cash_deployment_min_confidence", 80.0),
                step=5, min_val=50, max_val=95, unit="%",
            ),
            _setting_row(
                "cash_floor_gbp",
                "Cash Floor",
                "The smallest amount the system will ever invest in a single "
                "trade. If a position would be smaller than this, it skips "
                "the trade entirely. Prevents tiny pointless trades.",
                limits.get("cash_floor_gbp", 20.0),
                step=5, min_val=5, max_val=100, unit="£",
            ),

        ], style=_section_style()),

        # ── Paper Trading ─────────────────────────────────────────────────
        html.Div([
            html.H3("Paper Trading", style=_section_title_style()),

            html.P(
                "Paper mode uses fake money so you can test changes safely "
                "before risking real capital. When you switch paper mode ON, "
                "all live trading stops immediately.",
                style={"color": "#888", "fontSize": "13px",
                       "marginBottom": "15px", "lineHeight": "1.5"},
            ),

            # Paper mode toggle row
            html.Div([
                html.Div([
                    html.Span("Paper Trading Mode", style={
                        "color": "#fff", "fontSize": "14px",
                    }),
                    html.P(
                        "Turn this ON to trade with fake money. Turn it OFF "
                        "to trade with real money. Open positions won't be "
                        "managed while switched off.",
                        style={"color": "#666", "fontSize": "12px",
                               "margin": "4px 0 0 0", "lineHeight": "1.4"},
                    ),
                ], style={"flex": "1"}),
                dcc.Checklist(
                    id="settings-paper-toggle",
                    options=[{"label": "  Enabled", "value": "on"}],
                    value=["on"] if is_paper else [],
                    style={"color": "#ffaa00", "fontSize": "14px"},
                ),
            ], style={
                "display": "flex", "alignItems": "center",
                "justifyContent": "space-between", "padding": "10px 0",
            }),

            # Warning when paper mode is off
            html.Div(
                "⚠️  Paper mode is OFF — you are trading with real money. "
                "Any changes you save will affect live trades.",
                id="settings-live-warning",
                style={
                    "backgroundColor": "rgba(255,68,68,0.1)",
                    "border": "1px solid #ff4444",
                    "borderRadius": "6px",
                    "padding": "10px 14px",
                    "color": "#ff4444",
                    "fontSize": "13px",
                    "marginTop": "10px",
                    "display": "none" if is_paper else "block",
                },
            ),

        ], style=_section_style()),

        # ── Save / Status ─────────────────────────────────────────────────
        html.Div([
            html.Div(id="settings-save-status", style={
                "fontSize": "13px", "padding": "8px 0",
            }),
            html.Div([
                html.Button("💡 Recommended Settings", id="settings-recommend-btn",
                            n_clicks=0, style={
                    "backgroundColor": "transparent",
                    "border": "1px solid #333",
                    "color": "#888",
                    "padding": "10px 20px",
                    "borderRadius": "6px",
                    "cursor": "pointer",
                    "fontSize": "13px",
                }),
                html.Button("💾 Save Changes", id="settings-save-btn",
                            n_clicks=0, style={
                    "backgroundColor": "#00ff88",
                    "border": "none",
                    "color": "#080808",
                    "padding": "10px 24px",
                    "borderRadius": "6px",
                    "cursor": "pointer",
                    "fontWeight": "bold",
                    "fontSize": "14px",
                }),
            ], style={"display": "flex", "gap": "12px",
                      "justifyContent": "flex-end"}),
        ], style={
            "display": "flex", "justifyContent": "space-between",
            "alignItems": "center", "padding": "15px 0",
            "borderTop": "1px solid #222", "marginTop": "10px",
        }),

        # Hidden div to hold recommendation text
        html.Div(id="settings-recommendation-box", style={
            "display": "none",
        }),
    ])


# ═══════════════════════════════════════════════════════════════════════════════
# CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════

@callback(
    Output("settings-save-status", "children"),
    Output("settings-save-status", "style"),
    Input("settings-save-btn", "n_clicks"),
    [
        State("setting-max_open_positions", "value"),
        State("setting-max_position_pct", "value"),
        State("setting-stop_loss_pct", "value"),
        State("setting-take_profit_pct", "value"),
        State("setting-max_drawdown_pct", "value"),
        State("setting-daily_loss_limit_pct", "value"),
        State("setting-correlation_limit", "value"),
        State("setting-min_confidence_threshold", "value"),
        State("setting-cash_deployment_threshold_pct", "value"),
        State("setting-cash_deployment_min_confidence", "value"),
        State("setting-cash_floor_gbp", "value"),
        State("settings-paper-toggle", "value"),
    ],
    prevent_initial_call=True,
)
def save_settings(
    n_clicks,
    max_open_positions,
    max_position_pct,
    stop_loss_pct,
    take_profit_pct,
    max_drawdown_pct,
    daily_loss_limit_pct,
    correlation_limit,
    min_confidence_threshold,
    cash_deployment_threshold_pct,
    cash_deployment_min_confidence,
    cash_floor_gbp,
    paper_toggle,
):
    if not n_clicks:
        return no_update, no_update

    try:
        new_limits = {
            "max_drawdown_pct": float(max_drawdown_pct or 8.0),
            "max_position_pct": float(max_position_pct or 15.0),
            "max_open_positions": int(max_open_positions or 8),
            "min_confidence_threshold": float(min_confidence_threshold or 65.0),
            "cash_floor_gbp": float(cash_floor_gbp or 20.0),
            "daily_loss_limit_pct": float(daily_loss_limit_pct or 3.0),
            "correlation_limit": float(correlation_limit or 0.85),
            "stop_loss_pct": float(stop_loss_pct or 5.0),
            "take_profit_pct": float(take_profit_pct or 15.0),
            "paper_trading_mode": bool(paper_toggle and "on" in paper_toggle),
            "cash_deployment_threshold_pct": float(
                cash_deployment_threshold_pct or 40.0
            ),
            "cash_deployment_min_confidence": float(
                cash_deployment_min_confidence or 80.0
            ),
        }

        with open(RISK_LIMITS_FILE, "w") as f:
            json.dump(new_limits, f, indent=2)

        return (
            "✅ Settings saved successfully. Changes take effect on the next scan.",
            {"fontSize": "13px", "padding": "8px 0", "color": "#00ff88"},
        )
    except Exception as e:
        return (
            f"❌ Error saving settings: {str(e)}",
            {"fontSize": "13px", "padding": "8px 0", "color": "#ff4444"},
        )


@callback(
    Output("settings-live-warning", "style"),
    Input("settings-paper-toggle", "value"),
    prevent_initial_call=True,
)
def toggle_live_warning(paper_toggle):
    is_paper = paper_toggle and "on" in paper_toggle
    return {
        "backgroundColor": "rgba(255,68,68,0.1)",
        "border": "1px solid #ff4444",
        "borderRadius": "6px",
        "padding": "10px 14px",
        "color": "#ff4444",
        "fontSize": "13px",
        "marginTop": "10px",
        "display": "none" if is_paper else "block",
    }


@callback(
    Output("settings-recommendation-box", "children"),
    Output("settings-recommendation-box", "style"),
    Input("settings-recommend-btn", "n_clicks"),
    prevent_initial_call=True,
)
def show_recommendations(n_clicks):
    if not n_clicks:
        return no_update, no_update

    from execution.order_manager import load_portfolio_state, get_portfolio_value

    state = load_portfolio_state()
    portfolio_value = get_portfolio_value(state)

    # Recommend positions based on portfolio size
    if portfolio_value < 300:
        rec_positions = 3
    elif portfolio_value < 500:
        rec_positions = 4
    elif portfolio_value < 750:
        rec_positions = 5
    elif portfolio_value < 1500:
        rec_positions = 6
    else:
        rec_positions = 8

    rec_text = (
        f"💡 Based on your £{portfolio_value:,.0f} portfolio:\n"
        f"  • Max positions: {rec_positions} "
        f"(~£{portfolio_value / rec_positions:,.0f} per trade)\n"
        f"  • Keep stop loss at 5% — proven during paper testing\n"
        f"  • Keep take profit at 15% — gives a 3:1 reward/risk\n"
        f"  • Min confidence 65% — lower risks weaker signals"
    )

    return (
        html.Div([
            html.Pre(rec_text, style={
                "color": "#00aaff", "fontSize": "13px",
                "margin": "0", "whiteSpace": "pre-wrap",
                "fontFamily": "Segoe UI, sans-serif",
            }),
        ], style={
            "backgroundColor": "rgba(0,170,255,0.08)",
            "border": "1px solid rgba(0,170,255,0.3)",
            "borderRadius": "6px",
            "padding": "12px 16px",
        }),
        {
            "display": "block",
            "marginBottom": "15px",
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER COMPONENTS
# ═══════════════════════════════════════════════════════════════════════════════

def _status_card(label, value, color):
    return html.Div([
        html.P(label, style={
            "color": "#888", "fontSize": "11px",
            "margin": "0 0 4px 0", "textTransform": "uppercase",
            "letterSpacing": "0.5px",
        }),
        html.P(value, style={
            "color": color, "fontSize": "17px",
            "fontWeight": "bold", "margin": "0",
        }),
    ], style={
        "backgroundColor": "#111",
        "borderRadius": "8px",
        "padding": "12px 18px",
        "flex": "1",
        "minWidth": "130px",
    })


def _setting_row(setting_id, label, description, value, step=1,
                 min_val=0, max_val=100, unit="%"):
    """Build a single setting row with label, description, and input."""
    return html.Div([
        html.Div([
            html.Div([
                html.Span(label, style={
                    "color": "#fff", "fontSize": "14px",
                }),
                html.P(description, style={
                    "color": "#666", "fontSize": "12px",
                    "margin": "4px 0 0 0", "lineHeight": "1.4",
                    "maxWidth": "500px",
                }),
            ], style={"flex": "1"}),
            html.Div([
                dcc.Input(
                    id=f"setting-{setting_id}",
                    type="number",
                    value=value,
                    step=step,
                    min=min_val,
                    max=max_val,
                    style={
                        "width": "80px",
                        "textAlign": "right",
                        "backgroundColor": "#1a1a1a",
                        "border": "1px solid #333",
                        "borderRadius": "4px",
                        "color": "#fff",
                        "padding": "6px 10px",
                        "fontSize": "14px",
                    },
                ),
                html.Span(unit, style={
                    "color": "#666", "fontSize": "13px",
                    "minWidth": "20px", "marginLeft": "6px",
                }),
            ], style={
                "display": "flex", "alignItems": "center",
            }),
        ], style={
            "display": "flex", "alignItems": "center",
            "justifyContent": "space-between",
        }),
    ], style={
        "padding": "14px 0",
        "borderBottom": "1px solid #1a1a1a",
    })


def _section_style():
    return {
        "backgroundColor": "#111",
        "borderRadius": "8px",
        "padding": "20px",
        "marginBottom": "20px",
    }


def _section_title_style():
    return {
        "color": "#888",
        "fontSize": "14px",
        "marginBottom": "15px",
        "margin": "0 0 15px 0",
    }