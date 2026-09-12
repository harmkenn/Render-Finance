from __future__ import annotations

import threading
import time
from functools import lru_cache

import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from dash import dash_table, dcc, html


YAHOO_REQUEST_INTERVAL_SECONDS = 2.0
_yahoo_request_lock = threading.Lock()
_last_yahoo_request_at = 0.0


def wait_for_yahoo_request_slot() -> None:
    global _last_yahoo_request_at
    with _yahoo_request_lock:
        elapsed = time.monotonic() - _last_yahoo_request_at
        if elapsed < YAHOO_REQUEST_INTERVAL_SECONDS:
            time.sleep(YAHOO_REQUEST_INTERVAL_SECONDS - elapsed)
        _last_yahoo_request_at = time.monotonic()


@lru_cache(maxsize=64)
def fetch_history(ticker: str, period: str = "10d", interval: str = "5m") -> pd.DataFrame:
    wait_for_yahoo_request_slot()
    return yf.Ticker(ticker).history(period=period, interval=interval, prepost=True)


@lru_cache(maxsize=16)
def fetch_daily_histories(tickers: tuple[str, ...]) -> pd.DataFrame:
    wait_for_yahoo_request_slot()
    return yf.download(tickers=list(tickers), period="3mo", interval="1d", progress=False, auto_adjust=False, group_by="ticker")


def clear_caches() -> None:
    fetch_history.cache_clear()
    fetch_daily_histories.cache_clear()


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
            figure.add_vrect(x0=premarket.index[0], x1=premarket.index[-1], fillcolor="rgba(255, 165, 0, 0.16)", layer="below", line_width=0)
        if not after_hours.empty:
            figure.add_vrect(x0=after_hours.index[0], x1=after_hours.index[-1], fillcolor="rgba(128, 0, 128, 0.16)", layer="below", line_width=0)


def _metric(label: str, value: str, tone: str = "") -> html.Div:
    return html.Div([html.Div(label, className="intraday-label"), html.Div(value, className=f"intraday-value {tone}".strip())], className="intraday-metric")


def _stats_table(data: pd.DataFrame, ticker: str) -> dash_table.DataTable | html.Div:
    stats_data = get_ticker_daily_data(data, ticker)
    if stats_data.empty:
        return html.Div("No three-month daily statistics available.", className="empty-state")
    week_1, week_3, week_5 = stats_data.tail(5), stats_data.tail(15), stats_data.tail(25)
    rows = [("5 Week High", week_5["High"].max()), ("3 Week High", week_3["High"].max()), ("1 Week High", week_1["High"].max()), ("5 Week Avg", week_5["Close"].mean()), ("1 Week Low", week_1["Low"].min()), ("3 Week Low", week_3["Low"].min()), ("5 Week Low", week_5["Low"].min())]
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
                html.Div([html.Strong(ticker), html.Span(f"${latest:.2f}", className="intraday-sidebar-price"), html.Span(f"({percent_change:+.2f}%)", className=f"intraday-sidebar-change {tone}")], className="intraday-sidebar-line"),
                html.Div(html.Div(className=f"intraday-sidebar-marker {tone}", style={"left": f"{position:.2f}%"}), className="intraday-sidebar-bar"),
                html.Small(f"60-day range: ${low_60d:.2f} - ${high_60d:.2f}", className="intraday-sidebar-range"),
            ], className="intraday-sidebar-row"))
        except Exception as error:
            content.append(html.Div([html.Strong(ticker), html.Span(f"Error ({error})", className="intraday-sidebar-muted")], className="intraday-sidebar-row"))
    return content


def intraday_layout(tickers: list[str]) -> html.Div:
    ticker = tickers[0] if tickers else "TQQQ"
    return html.Div([
        html.Div([html.H2("Intraday Tape"), html.P("Track regular, pre-market, and after-hours price action in one view.", className="intro-copy")], className="section-header"),
        html.Div([dcc.Dropdown(id="intraday-ticker", options=[{"label": item, "value": item} for item in tickers], value=ticker, clearable=False, className="intraday-ticker"), html.Button("Refresh chart", id="intraday-refresh", className="add-button")], className="intraday-controls"),
        html.Div(id="intraday-status", className="status-message"),
        html.Div(id="intraday-metrics", className="intraday-grid"),
        html.Div([html.Section([html.Div([html.H3("Daily range statistics"), html.Span("3 months of daily closes", className="section-caption")], className="chart-heading"), html.Div(id="intraday-stats")], className="surface intraday-stats"), html.Section([dcc.Graph(id="intraday-price", config={"displayModeBar": False})], className="surface intraday-chart")], className="intraday-top-grid"),
        html.Section([dcc.Graph(id="intraday-volume", config={"displayModeBar": False})], className="surface intraday-chart"),
        html.Section([html.Div([html.H3("Recent observations"), html.Span("Newest first", className="section-caption")], className="chart-heading"), html.Div(id="intraday-data")], className="surface intraday-data-section"),
    ], id="intraday-content", style={"display": "none"})


def render_intraday(symbol: str, refresh: int | None = None):
    if refresh is not None:
        clear_caches()
    symbol = (symbol or "TQQQ").strip().upper()
    try:
        history = _as_eastern(fetch_history(symbol))
        daily = fetch_daily_histories((symbol,))
        if history.empty:
            return f"No data found for {symbol}. Check the symbol and try again.", [], html.Div(), {}, {}, html.Div()

        latest_price = float(history["Close"].iloc[-1])
        regular_hours = history.between_time("09:30", "16:00")
        daily_closes = regular_hours.groupby(regular_hours.index.date).last()["Close"]
        last_close = float(daily_closes.iloc[-1]) if not daily_closes.empty else latest_price
        price_diff = latest_price - last_close
        percent_diff = price_diff / last_close * 100 if last_close else 0
        tone = "positive" if percent_diff >= 0 else "negative"

        recent_rows = history[["Close", "Volume"]].iloc[::-1].reset_index()
        recent_rows["Datetime"] = recent_rows.iloc[:, 0].dt.strftime("%Y-%m-%d %H:%M")
        recent_rows = recent_rows[["Datetime", "Close", "Volume"]].head(250)
        recent_rows["Close"] = recent_rows["Close"].map(lambda value: f"${value:,.2f}")
        recent_rows["Volume"] = recent_rows["Volume"].map(lambda value: f"{int(value):,}")
        table = dash_table.DataTable(data=recent_rows.to_dict("records"), columns=[{"name": name, "id": name} for name in recent_rows.columns], page_size=20, sort_action="native", style_table={"overflowX": "auto"}, style_header={"fontWeight": "600", "color": "#91a39a", "backgroundColor": "#202f27", "border": "0"}, style_cell={"backgroundColor": "#17221d", "color": "#e8f1eb", "border": "0", "padding": "8px 10px", "fontSize": "11px", "textAlign": "right"}, style_cell_conditional=[{"if": {"column_id": "Datetime"}, "textAlign": "left"}])

        price_figure = go.Figure()
        add_market_hours_shading(price_figure, history)
        price_figure.add_trace(go.Scatter(x=history.index, y=history["Close"], mode="lines", name="Price", line={"color": "#9cddbe", "width": 1.8}))
        price_figure.update_layout(template="plotly_dark", title=f"{symbol} intraday price", height=430, margin={"l": 20, "r": 20, "t": 45, "b": 20}, hovermode="x unified", xaxis_title="US/Eastern", yaxis_title="Price ($)")

        volume_figure = go.Figure()
        add_market_hours_shading(volume_figure, history)
        volume_figure.add_trace(go.Bar(x=history.index, y=history["Volume"], name="Volume", marker_color="#91a39a"))
        volume_figure.update_layout(template="plotly_dark", title=f"{symbol} intraday volume", height=300, margin={"l": 20, "r": 20, "t": 45, "b": 20}, hovermode="x unified", xaxis_title="US/Eastern", yaxis_title="Volume")

        metrics = [_metric("Latest price", f"${latest_price:,.2f}"), _metric("Session close", f"${last_close:,.2f}"), _metric("Change", f"{price_diff:+.2f} ({percent_diff:+.2f}%)", tone), _metric("Bars loaded", f"{len(history):,}")]
        return f"{symbol} · Updated through {history.index[-1].strftime('%Y-%m-%d %H:%M %Z')}", metrics, _stats_table(daily, symbol), price_figure, volume_figure, table
    except Exception as error:
        return f"Error fetching {symbol}: {error}", [], html.Div(), {}, {}, html.Div()