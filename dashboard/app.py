import dash
from dash import dcc, html, Output, Input
from datetime import datetime

app = dash.Dash(
    __name__,
    suppress_callback_exceptions=True,
    title="TradeCore"
)

app.layout = html.Div([

    # ── Header ───────────────────────────────────────────────────────────────
    html.Div([
        html.Div([
            html.H1("⚡ TradeCore", style={
                "color": "#00ff88",
                "fontWeight": "bold",
                "fontSize": "28px",
                "margin": "0"
            }),
            html.P("Algorithmic Trading System", style={
                "color": "#888",
                "margin": "0",
                "fontSize": "13px"
            })
        ]),
        html.Div(id="last-updated", style={
            "color": "#888",
            "fontSize": "12px",
            "textAlign": "right"
        })
    ], style={
        "display": "flex",
        "justifyContent": "space-between",
        "alignItems": "center",
        "padding": "20px 30px",
        "borderBottom": "1px solid #222",
        "backgroundColor": "#0a0a0a"
    }),

    # ── Navigation Tabs ───────────────────────────────────────────────────────
    dcc.Tabs(id="tabs", value="portfolio", children=[
        dcc.Tab(label="💰 Portfolio", value="portfolio",
                style={"backgroundColor": "#111", "color": "#888",
                       "border": "none"},
                selected_style={"backgroundColor": "#0a0a0a",
                                "color": "#00ff88",
                                "borderTop": "2px solid #00ff88",
                                "border": "none"}),
        dcc.Tab(label="📡 Signals", value="signals",
                style={"backgroundColor": "#111", "color": "#888",
                       "border": "none"},
                selected_style={"backgroundColor": "#0a0a0a",
                                "color": "#00ff88",
                                "borderTop": "2px solid #00ff88",
                                "border": "none"}),
        dcc.Tab(label="🛡️ Risk", value="risk",
                style={"backgroundColor": "#111", "color": "#888",
                       "border": "none"},
                selected_style={"backgroundColor": "#0a0a0a",
                                "color": "#00ff88",
                                "borderTop": "2px solid #00ff88",
                                "border": "none"}),
        dcc.Tab(label="📊 Backtest", value="backtest",
                style={"backgroundColor": "#111", "color": "#888",
                       "border": "none"},
                selected_style={"backgroundColor": "#0a0a0a",
                                "color": "#00ff88",
                                "borderTop": "2px solid #00ff88",
                                "border": "none"}),
        dcc.Tab(label="💳 Wallet", value="wallet",
                style={"backgroundColor": "#111", "color": "#888",
                       "border": "none"},
                selected_style={"backgroundColor": "#0a0a0a",
                                "color": "#00ff88",
                                "borderTop": "2px solid #00ff88",
                                "border": "none"}),
        dcc.Tab(label="⚙️ Settings", value="settings",
                style={"backgroundColor": "#111", "color": "#888",
                       "border": "none"},
                selected_style={"backgroundColor": "#0a0a0a",
                                "color": "#00ff88",
                                "borderTop": "2px solid #00ff88",
                                "border": "none"}),
    ], style={"backgroundColor": "#111", "border": "none"}),

    # ── Tab Content ───────────────────────────────────────────────────────────
    html.Div(id="tab-content", style={
        "padding": "20px 30px",
        "backgroundColor": "#0a0a0a",
        "minHeight": "calc(100vh - 120px)"
    }),

    # ── Settings layout always rendered — hidden when not on settings tab ─────
    # This ensures all settings callbacks register at startup regardless of
    # which tab is active. Display is toggled by the tab router below.
    html.Div(
        id="settings-persistent",
        style={"display": "none", "padding": "20px 30px",
               "backgroundColor": "#0a0a0a"}
    ),

    # ── Auto Refresh Every 60 Seconds ─────────────────────────────────────────
    dcc.Interval(id="refresh", interval=60000, n_intervals=0)

], style={"backgroundColor": "#0a0a0a", "minHeight": "100vh",
          "fontFamily": "Segoe UI, sans-serif"})


# ── Tab Router ────────────────────────────────────────────────────────────────
@app.callback(
    Output("tab-content", "children"),
    Output("tab-content", "style"),
    Output("settings-persistent", "children"),
    Output("settings-persistent", "style"),
    Output("last-updated", "children"),
    Input("tabs", "value"),
    Input("refresh", "n_intervals")
)
def render_tab(tab, _):
    from dashboard.layouts import portfolio, signals, risk, backtest, wallet, settings
    timestamp = f"Last updated: {datetime.now().strftime('%H:%M:%S')}"

    tab_style_visible = {
        "padding": "20px 30px",
        "backgroundColor": "#0a0a0a",
        "minHeight": "calc(100vh - 120px)"
    }
    tab_style_hidden = {
        "padding": "20px 30px",
        "backgroundColor": "#0a0a0a",
        "minHeight": "calc(100vh - 120px)",
        "display": "none"
    }
    settings_visible = {
        "display": "block",
        "padding": "20px 30px",
        "backgroundColor": "#0a0a0a"
    }
    settings_hidden = {
        "display": "none",
        "padding": "20px 30px",
        "backgroundColor": "#0a0a0a"
    }

    # Always render settings in the persistent div
    settings_content = settings.layout()

    if tab == "portfolio":
        return portfolio.layout(), tab_style_visible, settings_content, settings_hidden, timestamp
    elif tab == "signals":
        return signals.layout(), tab_style_visible, settings_content, settings_hidden, timestamp
    elif tab == "risk":
        return risk.layout(), tab_style_visible, settings_content, settings_hidden, timestamp
    elif tab == "backtest":
        return backtest.layout(), tab_style_visible, settings_content, settings_hidden, timestamp
    elif tab == "wallet":
        return wallet.layout(), tab_style_visible, settings_content, settings_hidden, timestamp
    elif tab == "settings":
        # Hide tab-content, show settings-persistent
        return html.Div(), tab_style_hidden, settings_content, settings_visible, timestamp

    return html.Div("Tab not found"), tab_style_visible, settings_content, settings_hidden, timestamp


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8050)