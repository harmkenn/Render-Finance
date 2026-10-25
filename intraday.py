from __future__ import annotations

import threading
import time
from datetime import date, timedelta
from functools import lru_cache

import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from dash import Dash, Input, Output, State, dash_table, dcc, html

# =============================================================================
# CONSTANTS & GLOBAL RATE LIMITING
# =============================================================================

YAHOO_REQUEST_INTERVAL_SECONDS = 2.0
_yahoo_request_lock = threading.Lock()
_last_yahoo_request_at = 0.0

DATA_COLUMNS = [
    "Open", "High", "Low", "Close", "Volume", "Dividends", "Yield",
    "20-day MA", "50-day MA", "200-day MA", "RSI", "MFI", "ATR",
    "Volatility", "Open▲", "Open%", "High▲", "High%", "Low▲", "Low%",
    "Close▲", "Close%",
]


def wait_for_yahoo_request_slot() -> None:
    global _last_yahoo_request_at
    with _yahoo_request_lock:
        elapsed = time.monotonic() - _last_yahoo_request_at
        if elapsed < YAHOO_REQUEST_INTERVAL_SECONDS:
            time.sleep(YAHOO_REQUEST_INTERVAL_SECONDS - elapsed)
        _last_yahoo_request_at = time.monotonic()


# =============================================================================
# DATA FETCHING & CACHING
# =============================================================================

@lru_cache(maxsize=64)
def fetch_history(ticker: str, period: str = "10d", interval: str = "5m") -> pd.DataFrame:
    wait_for_yahoo_request_slot()
    return yf.Ticker(ticker).history(period=period, interval=interval, prepost=True)


@lru_cache(maxsize=16)
def fetch_daily_histories(tickers: tuple[str, ...]) -> pd.DataFrame:
    wait_for_yahoo_request_slot()
    return yf.download(
        tickers=list(tickers),
        period="3mo",
        interval="1d",
        progress=False,
        auto_adjust=False,
        group_by="ticker",
    )


@lru_cache(maxsize=64)
def fetch_stock_history(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    wait_for_yahoo_request_slot()
    inclusive_end = (date.fromisoformat(end_date) + timedelta(days=1)).isoformat()
    return yf.Ticker(ticker).history(
        start=start_date,
        end=inclusive_end,
        interval="1d",
        auto_adjust=False,
        actions=True,
    )


def clear_intraday_caches() -> None:
    fetch_history.cache_clear()
    fetch_daily_histories.cache_clear()


# Option 1 Alias: retain backward compatibility for `from intraday import clear_caches`
clear_caches = clear_intraday_caches


def clear_stock_history_cache() -> None:
    fetch_stock_history.cache_clear()


# =============================================================================
# HELPER CALCULATIONS & UTILITIES
# =============================================================================

def get_ticker_daily_data(data: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if isinstance(data.columns, pd.MultiIndex):
        if ticker in data.columns.get_level_values(0):
            return data[ticker].dropna(how="all")
        if ticker in data.columns.get_level_values(1):
            return data.xs(ticker, axis=1, level=1).dropna(how="all")
        return pd.DataFrame()
    return data.dropna(how="all")


def _as_eastern(data: pd.DataFrame) -> pd.DataFrame:
    if data.index.tz is None:
        return data
    data = data.copy()
    data.index = data.index.tz_convert("America/New_York")
    return data


def add_market_hours_shading(figure: go.Figure, data: pd.DataFrame) -> None:
    if data.empty:
        return
    for trade_date in pd.Series(data.index.date).unique():
        session = data[data.index.date == trade_date]
        premarket = session.between_time("04:00", "09:29")
        after_hours = session.between_time("16:00", "20:00")
        if not premarket.empty:
            figure.add_vrect(
                x0=premarket.index[0],
                x1=premarket.index[-1],
                fillcolor="rgba(255, 165, 0, 0.16)",
                layer="below",
                line_width=0,
            )
        if not after_hours.empty:
            figure.add_vrect(
                x0=after_hours.index[0],
                x1=after_hours.index[-1],
                fillcolor="rgba(128, 0, 128, 0.16)",
                layer="below",
                line_width=0,
            )


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


def _metric(label: str, value: str, tone: str = "", css_prefix: str = "intraday") -> html.Div:
    return html.Div([
        html.Div(label, className=f"{css_prefix}-label"),
        html.Div(value, className=f"{css_prefix}-value {tone}".strip()),
    ], className=f"{css_prefix}-metric")


def _stats_table(data: pd.DataFrame, ticker: str) -> dash_table.DataTable | html.Div:
    stats_data = get_ticker_daily_data(data, ticker)
    if stats_data.empty:
        return html.Div("No three-month daily statistics available.", className="empty-state")
    week_1, week_3, week_5 = stats_data.tail(5), stats_data.tail(15), stats_data.tail(25)
    rows = [
        ("5 Week High", week_5["High"].max()),
        ("3 Week High", week_3["High"].max()),
        ("1 Week High", week_1["High"].max()),
        ("5 Week Avg", week_5["Close"].mean()),
        ("1 Week Low", week_1["Low"].min()),
        ("3 Week Low", week_3["Low"].min()),
        ("5 Week Low", week_5["Low"].min()),
    ]
    return dash_table.DataTable(
        data=[{"Metric": label, "Value": f"${value:,.2f}"} for label, value in rows],
        columns=[{"name": "Metric", "id": "Metric"}, {"name": "Value", "id": "Value"}],
        style_as_list_view=True,
        style_header={"fontWeight": "600", "color": "#91a39a", "backgroundColor": "#202f27", "border": "0"},
        style_cell={"backgroundColor": "#17221d", "color": "#e8f1eb", "border": "0", "padding": "9px 10px", "fontSize": "12px", "textAlign": "left"},
        style_data_conditional=[{"if": {"column_id": "Value"}, "textAlign": "right"}],
    )


def render_sidebar_range(tickers: list[str]) -> list[html.Component]:
    if not tickers:
        return [html.Div("No tickers configured.", className="intraday-sidebar-empty")]

    daily_histories = fetch_daily_histories(tuple(dict.fromkeys(tickers)))
    content: list[html.Component] = []
    for ticker in tickers:
        try:
            data = get_ticker_daily_data(daily_histories, ticker)
            if len(data) < 2:
                content.append(html.Div([html.Strong(ticker), html.Span("No data", className="intraday-sidebar-muted")], className="intraday-sidebar-row"))
                continue

            latest = float(data["Close"].iloc[-1])
            previous_close = float(data["Close"].iloc[-2])
            price_change = latest - previous_close
            percent_change = price_change / previous_close * 100 if previous_close else 0
            high_60d = float(data["High"].max())
            low_60d = float(data["Low"].min())
            position = ((latest - low_60d) / (high_60d - low_60d) * 100) if high_60d != low_60d else 50
            position = max(0, min(position, 100))
            tone = "positive" if percent_change >= 0 else "negative"

            content.append(html.Div([
                html.Div([
                    html.Strong(ticker),
                    html.Span(f"${latest:.2f}", className="intraday-sidebar-price"),
                    html.Span(f"({percent_change:+.2f}%)", className=f"intraday-sidebar-change {tone}"),
                ], className="intraday-sidebar-line"),
                html.Div(html.Div(className=f"intraday-sidebar-marker {tone}", style={"left": f"{position:.2f}%"}), className="intraday-sidebar-bar"),
                html.Small(f"60-day range: ${low_60d:.2f} -${high_60d:.2f}", className="intraday-sidebar-range"),
            ], className="intraday-sidebar-row"))
        except Exception as error:
            content.append(html.Div([html.Strong(ticker), html.Span(f"Error ({error})", className="intraday-sidebar-muted")], className="intraday-sidebar-row"))
    return content


# =============================================================================
# LAYOUT DEFINITIONS
# =============================================================================

def intraday_layout(tickers: list[str]) -> html.Div:
    ticker = tickers[0] if tickers else "TQQQ"
    return html.Div([
        html.Div([
            html.H2("Intraday Tape"),
            html.P("Track regular, pre-market, and after-hours price action in one view.", className="intro-copy"),
        ], className="section-header"),
        html.Div([
            dcc.Dropdown(
                id="intraday-ticker",
                options=[{"label": item, "value": item} for item in tickers],
                value=ticker,
                clearable=False,
                className="intraday-ticker",
            ),
            html.Button("Refresh chart", id="intraday-refresh", className="add-button"),
        ], className="intraday-controls"),
        html.Div(id="intraday-status", className="status-message"),
        html.Div(id="intraday-metrics", className="intraday-grid"),
        html.Div([
            html.Section([
                html.Div([
                    html.H3("Daily range statistics"),
                    html.Span("3 months of daily closes", className="section-caption"),
                ], className="chart-heading"),
                html.Div(id="intraday-stats"),
            ], className="surface intraday-stats"),
            html.Section([
                dcc.Graph(id="intraday-price", config={"displayModeBar": False}),
            ], className="surface intraday-chart"),
        ], className="intraday-top-grid"),
    ], id="intraday-content")


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
    ], id="stock-analyzer-content")


def main_layout(tickers: list[str] | None = None) -> html.Div:
    if tickers is None:
        tickers = ["TQQQ", "AAPL", "MSFT", "NVDA", "SPY"]

    return html.Div([
        dcc.Tabs(
            id="finance-tabs",
            value="intraday-tab",
            children=[
                dcc.Tab(label="Intraday Prices", value="intraday-tab", className="custom-tab", selected_className="custom-tab--selected"),
                dcc.Tab(label="Stock Analyzer", value="stock-analyzer-tab", className="custom-tab", selected_className="custom-tab--selected"),
            ],
            className="custom-tabs",
        ),
        html.Div(id="tab-content"),
    ], className="main-container")


# =============================================================================
# RENDER LOGIC
# =============================================================================

def render_intraday(symbol: str, refresh: int | None = None):
    if refresh is not None:
        clear_caches()
    symbol = (symbol or "TQQQ").strip().upper()
    try:
        history = _as_eastern(fetch_history(symbol))
        daily = fetch_daily_histories((symbol,))
        if history.empty:
            return f"No data found for {symbol}. Check the symbol and try again.", [], html.Div(), {}

        latest_price = float(history["Close"].iloc[-1])
        regular_hours = history.between_time("09:30", "16:00")
        daily_closes = regular_hours.groupby(regular_hours.index.date).last()["Close"]
        last_close = float(daily_closes.iloc[-1]) if not daily_closes.empty else latest_price
        price_diff = latest_price - last_close
        percent_diff = price_diff / last_close * 100 if last_close else 0
        tone = "positive" if percent_diff >= 0 else "negative"

        price_figure = go.Figure()
        add_market_hours_shading(price_figure, history)
        price_figure.add_trace(go.Scatter(x=history.index, y=history["Close"], mode="lines", name="Price", line={"color": "#9cddbe", "width": 1.8}))
        price_figure.update_layout(template="plotly_dark", title=f"{symbol} intraday price", height=430, margin={"l": 20, "r": 20, "t": 45, "b": 20}, hovermode="x unified", xaxis_title="US/Eastern", yaxis_title="Price ($)")

        metrics = [
            _metric("Latest price", f"${latest_price:,.2f}", css_prefix="intraday"),
            _metric("Session close", f"${last_close:,.2f}", css_prefix="intraday"),
            _metric("Change", f"{price_diff:+.2f} ({percent_diff:+.2f}%)", tone, css_prefix="intraday"),
            _metric("Bars loaded", f"{len(history):,}", css_prefix="intraday"),
        ]
        return f"{symbol} · Updated through {history.index[-1].strftime('%Y-%m-%d %H:%M %Z')}", metrics, _stats_table(daily, symbol), price_figure
    except Exception as error:
        return f"Error fetching {symbol}: {error}", [], html.Div(), {}


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
        _metric("Final RSI (30, 70)", latest("RSI"), css_prefix="stock-analyzer"),
        _metric("Final MFI (20, 80)", latest("MFI"), css_prefix="stock-analyzer"),
        _metric("ATR (14d)", f"{latest('ATR')} ({float(data['ATR'].iloc[-1]) / current_price * 100:.2f}%)" if pd.notna(data["ATR"].iloc[-1]) else "N/A", css_prefix="stock-analyzer"),
        _metric("Volatility (30d)", volatility_text, css_prefix="stock-analyzer"),
        _metric("Period high", f"${data['High'].max():.2f}", css_prefix="stock-analyzer"),
        _metric("Period low", f"${data['Low'].min():.2f}", css_prefix="stock-analyzer"),
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
            css_prefix="stock-analyzer",
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


# =============================================================================
# DASH APPLICATION INITIALIZATION & CALLBACKS
# =============================================================================

DEFAULT_TICKERS = ["TQQQ", "AAPL", "MSFT", "NVDA", "SPY"]

app = Dash(__name__)
server = app.server  # WSGI server entry point for Gunicorn / Render

app.layout = main_layout(DEFAULT_TICKERS)


@app.callback(
    Output("tab-content", "children"),
    Input("finance-tabs", "value"),
)
def render_tab_content(tab: str):
    if tab == "intraday-tab":
        return intraday_layout(DEFAULT_TICKERS)
    elif tab == "stock-analyzer-tab":
        return stock_analyzer_layout(DEFAULT_TICKERS)
    return html.Div("Tab not found.")


@app.callback(
    [
        Output("intraday-status", "children"),
        Output("intraday-metrics", "children"),
        Output("intraday-stats", "children"),
        Output("intraday-price", "figure"),
    ],
    [
        Input("intraday-refresh", "n_clicks"),
        Input("intraday-ticker", "value"),
    ],
    prevent_initial_call=False,
)
def update_intraday(n_clicks: int | None, ticker: str):
    return render_intraday(ticker, refresh=n_clicks)


@app.callback(
    [
        Output("stock-analyzer-status", "children"),
        Output("stock-analyzer-metrics", "children"),
        Output("stock-analyzer-price", "figure"),
        Output("stock-analyzer-indicators", "figure"),
        Output("stock-analyzer-statistics", "children"),
        Output("stock-analyzer-data", "children"),
    ],
    [
        Input("stock-analyzer-refresh", "n_clicks"),
        Input("stock-analyzer-dividends-only", "value"),
    ],
    [
        State("stock-analyzer-ticker", "value"),
        State("stock-analyzer-dates", "start_date"),
        State("stock-analyzer-dates", "end_date"),
    ],
    prevent_initial_call=False,
)
def update_stock_analyzer(n_clicks: int | None, dividends_only: list[str], ticker: str, start_date: str, end_date: str):
    show_divs = "dividends" in (dividends_only or [])
    return render_stock_analysis(ticker, start_date, end_date, dividends_only=show_divs)


if __name__ == "__main__":
    app.run_server(debug=True)
