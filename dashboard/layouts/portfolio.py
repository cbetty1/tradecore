from dash import html, dcc, callback, Output, Input
import plotly.graph_objects as go
import json
import os
from data.price_feed import get_latest_price
from database.queries import get_snapshots
from execution.order_manager import load_portfolio_state, get_portfolio_value

STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "portfolio_state.json")


def get_position_rows(state: dict) -> list:
    """Build position rows with live prices and P&L."""
    rows = []
    for ticker, pos in state["positions"].items():
        current_price = get_latest_price(ticker)
        if not current_price:
            continue

        entry_price = pos["entry_price"]
        shares = pos["shares"]
        invested = pos["invested"]
        current_value = shares * current_price
        pnl = current_value - invested
        pnl_pct = (pnl / invested) * 100

        pnl_color = "#00ff88" if pnl >= 0 else "#ff4444"
        arrow = "▲" if pnl >= 0 else "▼"

        rows.append(html.Tr([
            html.Td(ticker, style={"color": "#fff", "fontWeight": "bold"}),
            html.Td(f"{shares:.4f}", style={"color": "#aaa"}),
            html.Td(f"£{entry_price:.2f}", style={"color": "#aaa"}),
            html.Td(f"£{current_price:.2f}", style={"color": "#fff"}),
            html.Td(f"£{invested:.2f}", style={"color": "#aaa"}),
            html.Td(f"£{current_value:.2f}", style={"color": "#fff"}),
            html.Td(
                f"{arrow} £{abs(pnl):.2f} ({pnl_pct:+.1f}%)",
                style={"color": pnl_color, "fontWeight": "bold"}
            ),
        ]))
    return rows


def build_equity_chart(snapshots: list) -> go.Figure:
    """Build equity curve chart from portfolio snapshots."""
    if not snapshots:
        fig = go.Figure()
        fig.update_layout(
            paper_bgcolor="#111",
            plot_bgcolor="#111",
            font_color="#888",
            title="No data yet — equity curve will appear here"
        )
        return fig

    dates = [s["snapshot_date"] for s in reversed(list(snapshots))]
    values = [s["total_value"] for s in reversed(list(snapshots))]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates,
        y=values,
        mode="lines",
        fill="tozeroy",
        line=dict(color="#00ff88", width=2),
        fillcolor="rgba(0,255,136,0.1)",
        name="Portfolio Value"
    ))

    fig.update_layout(
        paper_bgcolor="#111",
        plot_bgcolor="#111",
        font_color="#888",
        margin=dict(l=20, r=20, t=20, b=20),
        xaxis=dict(gridcolor="#222", showgrid=True),
        yaxis=dict(gridcolor="#222", showgrid=True),
        showlegend=False,
        hovermode="x unified"
    )
    return fig


def layout():
    """Build and return the full portfolio layout."""
    state = load_portfolio_state()
    portfolio_value = get_portfolio_value(state)
    cash = state["cash"]
    starting_capital = state["starting_capital"]
    invested = portfolio_value - cash
    total_pnl = portfolio_value - starting_capital
    total_pnl_pct = (total_pnl / starting_capital) * 100
    snapshots = get_snapshots(90)

    pnl_color = "#00ff88" if total_pnl >= 0 else "#ff4444"
    pnl_arrow = "▲" if total_pnl >= 0 else "▼"

    # ── Summary Cards ─────────────────────────────────────────────────────────
    cards = html.Div([
        _card("Portfolio Value", f"£{portfolio_value:,.2f}", "#fff"),
        _card("Total Profit/Loss",
              f"{pnl_arrow} £{abs(total_pnl):,.2f} ({total_pnl_pct:+.1f}%)",
              pnl_color),
        _card("Cash Available", f"£{cash:,.2f}", "#00aaff"),
        _card("Invested", f"£{invested:,.2f}", "#ffaa00"),
        _card("Starting Capital", f"£{starting_capital:,.2f}", "#888"),
    ], style={
        "display": "flex",
        "gap": "15px",
        "marginBottom": "25px",
        "flexWrap": "wrap"
    })

    # ── Equity Curve ──────────────────────────────────────────────────────────
    equity_chart = html.Div([
        html.H3("Equity Curve", style={"color": "#888",
                "fontSize": "14px", "marginBottom": "10px"}),
        dcc.Graph(
            figure=build_equity_chart(snapshots),
            config={"displayModeBar": False},
            style={"height": "250px"}
        )
    ], style={"backgroundColor": "#111", "borderRadius": "8px",
              "padding": "15px", "marginBottom": "25px"})

    # ── Open Positions Table ──────────────────────────────────────────────────
    position_rows = get_position_rows(state)

    positions_table = html.Div([
        html.H3("Open Positions", style={"color": "#888",
                "fontSize": "14px", "marginBottom": "10px"}),
        html.Table([
            html.Thead(html.Tr([
                html.Th("Ticker", style=_th()),
                html.Th("Shares", style=_th()),
                html.Th("Entry Price", style=_th()),
                html.Th("Current Price", style=_th()),
                html.Th("Invested", style=_th()),
                html.Th("Current Value", style=_th()),
                html.Th("P&L", style=_th()),
            ])),
            html.Tbody(
                position_rows if position_rows else [
                    html.Tr(html.Td(
                        "No open positions",
                        colSpan=7,
                        style={"color": "#888", "textAlign": "center",
                               "padding": "20px"}
                    ))
                ]
            )
        ], style={"width": "100%", "borderCollapse": "collapse"})
    ], style={"backgroundColor": "#111", "borderRadius": "8px", "padding": "15px"})

    return html.Div([cards, equity_chart, positions_table])


def _card(label: str, value: str, color: str) -> html.Div:
    """Build a summary card."""
    return html.Div([
        html.P(label, style={"color": "#888", "fontSize": "12px",
                             "margin": "0 0 5px 0"}),
        html.P(value, style={"color": color, "fontSize": "20px",
                             "fontWeight": "bold", "margin": "0"})
    ], style={
        "backgroundColor": "#111",
        "borderRadius": "8px",
        "padding": "15px 20px",
        "flex": "1",
        "minWidth": "150px"
    })


def _th() -> dict:
    """Table header style."""
    return {
        "color": "#888",
        "fontSize": "12px",
        "textAlign": "left",
        "padding": "8px 12px",
        "borderBottom": "1px solid #222"
    }