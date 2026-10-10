from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timedelta
import threading
import time

import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from dash import dash_table, dcc, html


CACHE_TTL_SECONDS = 300
DEFAULT_TICKER_LIMIT = 7
TIME_HORIZONS = ("6 Months", "1 Year", "2 Years", "YTD")
_comparison_cache: OrderedDict[
    tuple[tuple[str, ...], str, str],
    tuple[float, pd.DataFrame],
] = OrderedDict()
_comparison_cache_lock = threading.Lock()


def _download_comparison_history(
    tickers: tuple[str, ...], start: str, end: str
) -> pd.DataFrame:
    inclusive_end = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
    history = yf.download(
        tickers=list(tickers),
        start=start,
        end=inclusive_end,
        interval="1d",
        progress=False,
        auto_adjust=False,
        group_by="ticker",
        threads=False,
    )
    if not isinstance(history, pd.DataFrame) or history.empty:
        return pd.DataFrame()

    if isinstance(history.columns, pd.MultiIndex):
        if "Close" in history.columns.get_level_values(0):
            close_prices = history["Close"]
        elif "Close" in history.columns.get_level_values(1):
            close_prices = history.xs("Close", axis=1, level=1)
        else:
            return pd.DataFrame()
    elif "Close" in history.columns:
        close_prices = history[["Close"]].rename(columns={"Close": tickers[0]})
    else:
        return pd.DataFrame()

    if isinstance(close_prices, pd.Series):
        close_prices = close_prices.to_frame(name=tickers[0])
    close_prices.index.name = "Date"
    return close_prices.sort_index()


def fetch_comparison_history(
    tickers: tuple[str, ...],
    start: str,
    end: str,
) -> pd.DataFrame:
    key = (tuple(tickers), start, end)
    now = time.monotonic()
    with _comparison_cache_lock:
        cached = _comparison_cache.get(key)
        if cached is not None:
            cached_at, history = cached
            if now - cached_at < CACHE_TTL_SECONDS:
                _comparison_cache.move_to_end(key)
                return history
            del _comparison_cache[key]

    history = _download_comparison_history(*key)
    with _comparison_cache_lock:
        _comparison_cache[key] = (time.monotonic(), history)
        _comparison_cache.move_to_end(key)
        while len(_comparison_cache) > 64:
            _comparison_cache.popitem(last=False)
    return history


def clear_comparison_cache() -> None:
    with _comparison_cache_lock:
        _comparison_cache.clear()


def normalize_closing_prices(close_prices: pd.DataFrame) -> pd.DataFrame:
    if close_prices.empty:
        return pd.DataFrame(index=close_prices.index)

    filled = close_prices.ffill().bfill()
    normalized = pd.DataFrame(index=filled.index)
    for symbol in filled.columns:
        valid = filled[symbol].dropna()
        if valid.empty:
            continue
        first_price = valid.iloc[0]
        if first_price != 0:
            normalized[symbol] = (filled[symbol] / first_price) * 100
    normalized.index.name = "Date"
    return normalized


def compare_layout(tickers: list[str]) -> html.Div:
    initial_tickers = tickers[:DEFAULT_TICKER_LIMIT]
    return html.Div([
        html.Div([
            html.H2("Normalized Closing Prices"),
            html.P("Compare the relative performance of the tickers in your sidebar list.", className="intro-copy"),
        ], className="section-header"),
        html.Div([
            html.Div([
                html.Label("TICKERS TO COMPARE", className="setting-label"),
                dcc.Dropdown(
                    id="compare-tickers",
                    options=[{"label": ticker, "value": ticker} for ticker in tickers],
                    value=initial_tickers,
                    multi=True,
                    placeholder="Select one or more tickers",
                    className="compare-tickers",
                ),
            ], className="compare-ticker-control"),
            html.Div([
                html.Label("TIME HORIZON", className="setting-label"),
                dcc.Dropdown(
                    id="compare-horizon",
                    options=[{"label": horizon, "value": horizon} for horizon in TIME_HORIZONS],
                    value="1 Year",
                    clearable=False,
                    className="compare-horizon",
                ),
            ], className="compare-horizon-control"),
            html.Button("↻ Refresh comparison", id="compare-refresh", className="add-button"),
        ], className="compare-controls"),
        html.Div(id="compare-status", className="status-message"),
        html.Section(
            dcc.Graph(id="compare-chart", config={"displayModeBar": False}),
            className="surface compare-chart",
        ),
        html.Section([
            html.Div([
                html.H3("Normalized Prices Table"),
                html.Span("Base value = 100", className="section-caption"),
            ], className="chart-heading"),
            html.Div(id="compare-table"),
        ], className="surface compare-data-section"),
    ], id="compare-content", style={"display": "none"})


def render_comparison(
    tickers: list[str] | None,
    horizon: str | None,
    today: date | None = None,
) -> tuple[str, go.Figure, html.Component]:
    figure = go.Figure()
    figure.update_layout(template="plotly_dark")
    symbols = list(dict.fromkeys((ticker or "").strip().upper() for ticker in (tickers or []) if ticker and ticker.strip()))
    if not symbols:
        return "Select at least one ticker to display the comparison.", figure, html.Div()

    end_date = today or datetime.today().date()
    if horizon == "6 Months":
        start_date = end_date - timedelta(days=180)
    elif horizon == "2 Years":
        start_date = end_date - timedelta(days=730)
    elif horizon == "YTD":
        start_date = date(end_date.year, 1, 1)
    else:
        horizon = "1 Year"
        start_date = end_date - timedelta(days=365)

    close_prices = fetch_comparison_history(
        tuple(symbols),
        start_date.isoformat(),
        end_date.isoformat(),
    )
    normalized = normalize_closing_prices(close_prices)
    if normalized.empty or not len(normalized.columns):
        return (
            f"Could not retrieve historical data for: {', '.join(symbols)}. Verify the tickers and try again.",
            figure,
            html.Div(),
        )

    for symbol in normalized.columns:
        figure.add_trace(go.Scatter(
            x=normalized.index,
            y=normalized[symbol],
            mode="lines",
            name=str(symbol),
            hovertemplate="<b>%{fullData.name}</b><br>Date: %{x}<br>Normalized Value: %{y:.2f}<extra></extra>",
        ))
    figure.update_layout(
        template="plotly_dark",
        title=f"Normalized Performance ({horizon}): {', '.join(map(str, normalized.columns))}",
        xaxis_title="Date",
        yaxis_title="Normalized Price (Base = 100)",
        height=500,
        hovermode="x unified",
        margin={"l": 20, "r": 20, "t": 55, "b": 25},
    )

    table_data = normalized.reset_index()
    table_data["Date"] = pd.to_datetime(table_data["Date"]).dt.strftime("%Y-%m-%d")
    table_data = table_data.astype(object).where(pd.notna(table_data), None)
    table = dash_table.DataTable(
        data=table_data.to_dict("records"),
        columns=[{"name": str(column), "id": str(column)} for column in table_data.columns],
        page_size=25,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_header={"fontWeight": "600", "color": "#91a39a", "backgroundColor": "#202f27", "border": "0"},
        style_cell={"backgroundColor": "#17221d", "color": "#e8f1eb", "border": "0", "padding": "8px 10px", "fontSize": "11px", "textAlign": "right", "minWidth": "105px"},
        style_cell_conditional=[{"if": {"column_id": "Date"}, "textAlign": "left"}],
    )
    return f"Comparing {', '.join(map(str, normalized.columns))} · {len(normalized):,} daily observations", figure, table
