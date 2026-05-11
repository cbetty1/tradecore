from dash import html, dcc
import plotly.graph_objects as go
from backtest.engine import BacktestEngine
from backtest.metrics import calculate_metrics


def build_backtest_chart(result: dict) -> go.Figure:
    """Build equity curve from backtest result."""
    if not result or not result.get("equity_curve"):
        fig = go.Figure()
        fig.update_layout(
            paper_bgcolor="#111",
            plot_bgcolor="#111",
            font_color="#888"
        )
        return fig

    dates = [e["date"] for e in result["equity_curve"]]
    values = [e["portfolio_value"] for e in result["equity_curve"]]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates,
        y=values,
        mode="lines",
        fill="tozeroy",
        line=dict(color="#00aaff", width=2),
        fillcolor="rgba(0,170,255,0.1)",
        name="Backtest Value"
    ))

    fig.update_layout(
        paper_bgcolor="#111",
        plot_bgcolor="#111",
        font_color="#888",
        margin=dict(l=20, r=20, t=20, b=20),
        xaxis=dict(gridcolor="#222"),
        yaxis=dict(gridcolor="#222"),
        showlegend=False
    )
    return fig


def layout():
    """Build and return the backtest layout."""

    engine = BacktestEngine(starting_capital=10000)
    result = engine.run("NVDA", period="2y")
    metrics = calculate_metrics(result)

    total_return = metrics.get("total_return_pct", 0)
    return_color = "#00ff88" if total_return >= 0 else "#ff4444"

    return html.Div([

        html.H3("Backtest Results — NVDA (2 Year)",
                style={"color": "#888", "fontSize": "14px",
                       "marginBottom": "20px"}),

        # ── Metrics Cards ─────────────────────────────────────────────────────
        html.Div([
            _metric_card("Total Return",
                         f"{total_return:+.2f}%", return_color),
            _metric_card("Win Rate",
                         f"{metrics.get('win_rate_pct', 0):.1f}%", "#fff"),
            _metric_card("Sharpe Ratio",
                         f"{metrics.get('sharpe_ratio', 0):.2f}", "#fff"),
            _metric_card("Max Drawdown",
                         f"{metrics.get('max_drawdown_pct', 0):.2f}%", "#ffaa00"),
            _metric_card("Reward/Risk",
                         f"{metrics.get('reward_risk_ratio', 0):.2f}", "#00aaff"),
            _metric_card("Total Trades",
                         str(metrics.get("total_trades", 0)), "#fff"),
        ], style={"display": "flex", "gap": "15px",
                  "marginBottom": "25px", "flexWrap": "wrap"}),

        # ── Equity Curve ──────────────────────────────────────────────────────
        html.Div([
            html.H3("Backtest Equity Curve",
                    style={"color": "#888", "fontSize": "14px",
                           "marginBottom": "10px"}),
            dcc.Graph(
                figure=build_backtest_chart(result),
                config={"displayModeBar": False},
                style={"height": "300px"}
            )
        ], style={"backgroundColor": "#111", "borderRadius": "8px",
                  "padding": "15px", "marginBottom": "20px"}),

        # ── Trade Breakdown ───────────────────────────────────────────────────
        html.Div([
            html.H3("Trade Breakdown",
                    style={"color": "#888", "fontSize": "14px",
                           "marginBottom": "15px"}),
            _stat_row("Starting Capital",
                      f"£{metrics.get('starting_capital', 0):,.2f}"),
            _stat_row("Final Value",
                      f"£{metrics.get('final_value', 0):,.2f}"),
            _stat_row("Winning Trades",
                      str(metrics.get("winning_trades", 0))),
            _stat_row("Losing Trades",
                      str(metrics.get("losing_trades", 0))),
            _stat_row("Avg Win",
                      f"£{metrics.get('avg_win_gbp', 0):,.2f}"),
            _stat_row("Avg Loss",
                      f"£{metrics.get('avg_loss_gbp', 0):,.2f}"),
        ], style={"backgroundColor": "#111", "borderRadius": "8px",
                  "padding": "20px"}),
    ])


def _metric_card(label, value, color):
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
        "minWidth": "130px"
    })


def _stat_row(label, value):
    return html.Div([
        html.Span(label, style={"color": "#aaa", "fontSize": "13px"}),
        html.Span(value, style={"color": "#fff", "fontSize": "13px",
                                "fontWeight": "bold"})
    ], style={
        "display": "flex",
        "justifyContent": "space-between",
        "padding": "8px 0",
        "borderBottom": "1px solid #1a1a1a"
    })