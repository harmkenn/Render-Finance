from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from dash import dash_table, dcc, html


DATA_COLUMNS = [
    "Open", "High", "Low", "Close", "Volume", "Dividends", "Yield",
    "20-day MA", "50-day MA", "200-day MA", "RSI", "MFI", "ATR",
    "Volatility", "Open▲", "Open%", "High▲", "High%", "Low▲", "Low%",
    "Close▲", "Close%",
]


@lru_cache(maxsize=64)
def fetch_stock_history(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    inclusive_end = (date.fromisoformat(end_date) + timedelta(days=1)).isoformat()
    return yf.Ticker(ticker).history(
        start=start_date,
        end=inclusive_end,
        interval="1d",
        auto_adjust=False,
        actions=True,
    )


def clear_stock_history_cache() -> None:
    fetch_stock_history.cache_clear()


def calculate_indicators(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()
    close_delta = data["Close"].diff()
    gain = close_delta.where(close_delta > 0, 0).rolling(window=14).mean()
    loss = -close_delta.where(close_delta < 0, 0).rolling(window=14).mean()
    data["RSI"] = 100 - (100 / (1 + gain / loss))

    typical_price = (data["High"] + data["Low"] + data["Close"]) / 3
    money_flow = typical_price * data["Volume"]
    positive_flow = money_flow.where(
        typical_price > typical_price.shift(1), 0
    ).rolling(window=14).sum()
    negative_flow = money_flow.where(
        typical_price < typical_price.shift(1), 0
    ).rolling(window=14).sum()
    data["MFI"] = 100 - (100 / (1 + positive_flow / negative_flow))

    data["Daily Return"] = data["Close"].pct_change(fill_method=None)
    data["Volatility"] = data["Daily Return"].rolling(window=30).std() * (252**0.5)
    high_low = data["High"] - data["Low"]
    high_close = (data["High"] - data["Close"].shift()).abs()
    low_close = (data["Low"] - data["Close"].shift()).abs()
    data["ATR"] = pd.concat(
        [high_low, high_close, low_close], axis=1
    ).max(axis=1).rolling(window=14).mean()

    data["20-day MA"] = data["Close"].rolling(window=20).mean()
    data["50-day MA"] = data["Close"].rolling(window=50).mean()
    data["200-day MA"] = data["Close"].rolling(window=200).mean()
    previous_close = data["Close"].shift(1)
    for name in ("Open", "High", "Low", "Close"):
        data[f"{name}▲"] = data[name] - previous_close
        data[f"{name}%"] = (data[name] / previous_close - 1) * 100
    return data


def _empty_figure() -> go.Figure:
    figure = go.Figure()
    figure.update_layout(template="plotly_dark")
    return figure


def _metric(label: str, value: str) -> html.Div:
    return html.Div(
        [html.Div(label, className="stock-analyzer-label"),
         html.Div(value, className="stock-analyzer-value")],
        className="stock-analyzer-metric",
    )


def stock_analyzer_layout(tickers: list[str]) -> html.Div:
    today = date.today()
    start = today - timedelta(days=5 * 365)
    ticker = tickers[0] if tickers else "TQQQ"
    return html.Div([
        html.Div([
            html.H2("Stock Analyzer"),
            html.P("Explore daily price action, technical indicators, dividends, and historical statistics.", className="intro-copy"),
        ], className="section-header"),
        html.Div([
            dcc.Dropdown(
                id="stock-analyzer-ticker",
                options=[{"label": item, "value": item} for item in tickers],
                value=ticker,
                clearable=False,
                className="stock-analyzer-ticker",
            ),
            dcc.DatePickerRange(
                id="stock-analyzer-dates",
                start_date=start.isoformat(),
                end_date=today.isoformat(),
                max_date_allowed=today.isoformat(),
                initial_visible_month=today.isoformat(),
                display_format="YYYY-MM-DD",
                className="stock-analyzer-dates",
            ),
            html.Button("Analyze stock", id="stock-analyzer-refresh", className="add-button"),
        ], className="stock-analyzer-controls"),
        html.Div(id="stock-analyzer-status", className="status-message"),
        html.Div(id="stock-analyzer-metrics", className="stock-analyzer-grid"),
        html.Section(
            dcc.Graph(id="stock-analyzer-price", config={"displayModeBar": False}),
            className="surface stock-analyzer-chart",
        ),
        html.Section(
            dcc.Graph(id="stock-analyzer-indicators", config={"displayModeBar": False}),
            className="surface stock-analyzer-chart",
        ),
        html.Section([
            html.Div([
                html.H3("Key Statistics"),
                dcc.Checklist(
                    id="stock-analyzer-dividends-only",
                    options=[{"label": "Show only rows with dividends", "value": "dividends"}],
                    value=[],
                    className="stock-analyzer-checkbox",
                ),
            ], className="chart-heading"),
            html.Div(id="stock-analyzer-statistics", className="stock-analyzer-stats"),
            html.Div(id="stock-analyzer-data"),
        ], className="surface stock-analyzer-data-section"),
    ], id="stock-analyzer-content", style={"display": "none"})


def render_stock_analysis(
    symbol: str | None,
    start_date: str | None,
    end_date: str | None,
    dividends_only: bool = False,
):
    empty = _empty_figure()
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return "Select a stock ticker.", [], empty, empty, [], html.Div()
    if not start_date or not end_date:
        return "Choose both a start date and an end date.", [], empty, empty, [], html.Div()

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if start > end:
        return "Start date must be on or before the end date.", [], empty, empty, [], html.Div()

    history = fetch_stock_history(symbol, start.isoformat(), end.isoformat())
    if history.empty:
        return (
            f"No data found for {symbol} within the selected date range.",
            [], empty, empty, [], html.Div(),
        )

    data = history.copy()
    data.index.name = "Date"
    data = data.rename(columns={
        "open": "Open", "high": "High", "low": "Low", "close": "Close",
        "volume": "Volume", "dividends": "Dividends",
    })
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"Historical data is missing required columns: {', '.join(sorted(missing))}")

    if "Dividends" not in data.columns:
        data["Dividends"] = 0.0
    data["Dividends"] = data["Dividends"].fillna(0)
    data["Yield"] = (data["Dividends"] / data["Close"] * 100).fillna(0)
    data = calculate_indicators(data)

    current_price = float(data["Close"].iloc[-1])

    def latest(column: str) -> str:
        value = data[column].iloc[-1]
        return "N/A" if pd.isna(value) else f"{value:.2f}"

    volatility = data["Volatility"].iloc[-1]
    volatility_text = "N/A" if pd.isna(volatility) else f"{volatility:.2f} ({volatility / current_price * 100:.2f}%)"
    metrics = [
        _metric("Final RSI (30, 70)", latest("RSI")),
        _metric("Final MFI (20, 80)", latest("MFI")),
        _metric("ATR (14d)", f"{latest('ATR')} ({float(data['ATR'].iloc[-1]) / current_price * 100:.2f}%)" if pd.notna(data["ATR"].iloc[-1]) else "N/A"),
        _metric("Volatility (30d)", volatility_text),
        _metric("Period high", f"${data['High'].max():.2f}"),
        _metric("Period low", f"${data['Low'].min():.2f}"),
    ]

    price_figure = go.Figure()
    price_figure.add_trace(go.Candlestick(
        x=data.index, open=data["Open"], high=data["High"],
        low=data["Low"], close=data["Close"], name="OHLC",
    ))
    for window, color in ((20, "orange"), (50, "#4d9de0"), (200, "#e15554")):
        column = f"{window}-day MA"
        price_figure.add_trace(go.Scatter(
            x=data.index, y=data[column], mode="lines",
            name=column, line={"color": color},
        ))
    dividend_dates = data[data["Dividends"] > 0]
    if not dividend_dates.empty:
        price_figure.add_trace(go.Scatter(
            x=dividend_dates.index, y=dividend_dates["Close"],
            mode="markers", name="Dividend payout",
            marker={"symbol": "star", "size": 10, "color": "green"},
            text=[f"Dividend: ${amount:.2f}" for amount in dividend_dates["Dividends"]],
            hoverinfo="text+x+y",
        ))
    price_figure.update_layout(
        template="plotly_dark",
        title=f"{symbol} OHLC, Moving Averages and Dividends ({start} - {end})",
        xaxis_title="Date", yaxis_title="Price", xaxis_rangeslider_visible=False,
        height=500, margin={"l": 20, "r": 20, "t": 55, "b": 25},
    )

    indicator_figure = go.Figure()
    indicator_figure.add_trace(go.Scatter(x=data.index, y=data["RSI"], mode="lines", name="RSI", line={"color": "purple"}))
    indicator_figure.add_trace(go.Scatter(x=data.index, y=data["MFI"], mode="lines", name="MFI", line={"color": "brown"}))
    for level, color in ((70, "red"), (30, "green"), (80, "red"), (20, "green")):
        indicator_figure.add_hline(y=level, line={"color": color, "dash": "dot"})
    indicator_figure.update_layout(
        template="plotly_dark", title="RSI and MFI Indicators",
        xaxis_title="Date", yaxis_title="Value", height=350,
        margin={"l": 20, "r": 20, "t": 55, "b": 25},
    )

    statistics = []
    for label, delta, percent in (
        ("Open", "Open▲", "Open%"),
        ("High", "High▲", "High%"),
        ("Low", "Low▲", "Low%"),
        ("Close", "Close▲", "Close%"),
    ):
        delta_mean = data[delta].mean()
        percent_mean = data[percent].mean()
        statistics.append(_metric(
            f"Average {label} change",
            f"${delta_mean:.2f} · {percent_mean:.2f}%" if pd.notna(delta_mean) and pd.notna(percent_mean) else "N/A",
        ))

    table_data = data.loc[:, DATA_COLUMNS]
    if dividends_only:
        table_data = table_data[table_data["Dividends"] > 0]
    table_data = table_data.iloc[::-1].reset_index()
    table_data["Date"] = pd.to_datetime(table_data["Date"]).dt.strftime("%Y-%m-%d")
    table_data = table_data.astype(object).where(pd.notna(table_data), None)
    table = dash_table.DataTable(
        data=table_data.to_dict("records"),
        columns=[{"name": name, "id": name} for name in table_data.columns],
        page_size=25,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_header={"fontWeight": "600", "color": "#91a39a", "backgroundColor": "#202f27", "border": "0"},
        style_cell={"backgroundColor": "#17221d", "color": "#e8f1eb", "border": "0", "padding": "8px 10px", "fontSize": "11px", "textAlign": "right", "minWidth": "95px"},
        style_cell_conditional=[{"if": {"column_id": "Date"}, "textAlign": "left"}],
    )
    return f"{symbol} · {len(data):,} daily observations", metrics, price_figure, indicator_figure, statistics, table
