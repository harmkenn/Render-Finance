from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from dash import Dash, Input, Output, State, dcc, html

from fishing import PAGES, build_table, scrape_stock_top10
from intraday import clear_caches, intraday_layout, render_intraday, render_sidebar_range
from short_inspector import inspector_layout, render_inspector

DEFAULT_REFRESH_SECONDS = 30
DEFAULT_YELLOW_THRESHOLD = 100.0
DEFAULT_ORANGE_THRESHOLD = 150.0
DEFAULT_RED_THRESHOLD = 200.0
DEFAULT_TICKERS = ["TQQQ", "UPRO", "UDOW", "^VIX", "BNO"]


def parse_tickers(raw_tickers: str | None) -> list[str]:
    tickers = []
    for ticker in (raw_tickers or "").replace("\n", ",").split(","):
        cleaned = ticker.strip().upper()
        if cleaned and cleaned not in tickers:
            tickers.append(cleaned)
    return tickers or DEFAULT_TICKERS.copy()


def get_default_page_for(now: datetime) -> str:
    if now.weekday() >= 5:
        return "Top Daily Gainers"

    premarket_start = now.replace(hour=4, minute=0, second=0, microsecond=0)
    premarket_end = now.replace(hour=9, minute=30, second=0, microsecond=0)
    if premarket_start <= now < premarket_end:
        return "Premarket Movers"
    return "Top Daily Gainers"


def get_default_page() -> str:
    return get_default_page_for(datetime.now(ZoneInfo("America/New_York")))


app = Dash(__name__, title="Market Intelligence")
server = app.server


def sidebar() -> html.Aside:
    return html.Aside([
        html.Div([
            html.Div("MARKET INTELLIGENCE", className="eyebrow sidebar-eyebrow"),
            html.Div("by Ken Harmon", className="sidebar-credit"),
        ]),
        html.Button("☰  Settings", id="sidebar-toggle", className="sidebar-toggle"),
        html.Div([
            html.Label("INSPECTOR TICKERS", className="setting-label"),
            dcc.Textarea(id="inspector-tickers", value=", ".join(DEFAULT_TICKERS), placeholder="TQQQ, UPRO, ^VIX", className="sidebar-input ticker-input"),
            html.Span("comma separated", className="setting-suffix"),
            html.Label("APPLICATION", className="setting-label"),
            dcc.RadioItems(id="app-select", options=[{"label": "Fishing · Market tracker", "value": "fishing"}, {"label": "Parabolic short inspector", "value": "inspector"}, {"label": "Intraday tape", "value": "intraday"}], value="fishing", className="sidebar-control sidebar-radio", inputClassName="sidebar-radio-input", labelClassName="sidebar-radio-label"),
            html.Div([
                html.Label("MARKET VIEW", className="setting-label"),
                dcc.Dropdown(id="page-select", options=[{"label": name, "value": name} for name in PAGES], value=get_default_page(), clearable=False, className="sidebar-control"),
                html.Label("REFRESH INTERVAL", className="setting-label"),
                dcc.Input(id="refresh-seconds", type="number", min=10, max=600, step=5, value=DEFAULT_REFRESH_SECONDS, className="sidebar-input"),
                html.Span("seconds", className="setting-suffix"),
                html.Label("YELLOW THRESHOLD", className="setting-label"),
                dcc.Input(id="yellow-threshold", type="number", min=0, max=1000, step=5, value=DEFAULT_YELLOW_THRESHOLD, className="sidebar-input"),
                html.Span("% gain", className="setting-suffix"),
                html.Label("ORANGE THRESHOLD", className="setting-label"),
                dcc.Input(id="orange-threshold", type="number", min=0, max=1000, step=5, value=DEFAULT_ORANGE_THRESHOLD, className="sidebar-input"),
                html.Span("% gain", className="setting-suffix"),
                html.Label("RED THRESHOLD", className="setting-label"),
                dcc.Input(id="red-threshold", type="number", min=0, max=1000, step=5, value=DEFAULT_RED_THRESHOLD, className="sidebar-input"),
                html.Span("% gain", className="setting-suffix"),
            ], id="fishing-settings"),
        ], id="sidebar-settings", className="sidebar-settings"),
        html.Div([html.P("CURRENT PRICES & 60-DAY RANGE", className="eyebrow"), html.Div(id="intraday-sidebar-range")], id="intraday-sidebar-panel", className="intraday-sidebar-panel", style={"display": "none"}),
        html.Div([html.P("ACTIVE APP", className="eyebrow"), html.P("Fishing", id="sidebar-app-name", className="source-name"), html.P("Top market gainers with live filters", className="target-note")], className="sidebar-target"),
    ], id="sidebar", className="sidebar")


app.layout = html.Div([
    sidebar(),
    html.Main([
        html.Div([
            html.Header([html.Div([html.P("LIVE MARKET MONITOR", className="eyebrow")]), html.Div([html.Span("● Live", className="live-status"), html.Button("↻ Refresh now", id="manual-refresh", className="add-button")], className="header-actions")], className="topbar"),
            html.Div([html.Div([html.H2("Fishing"), html.P("Top market gainers, surfaced at the top of the app.", className="intro-copy")]), html.Div(id="refresh-summary", className="section-caption")], className="section-header"),
            html.Section([html.Div([html.Div([html.H3(id="table-heading"), html.Span("Click a ticker to open its StockAnalysis page.", className="section-caption")], className="chart-heading"), html.Div(id="status-message", className="status-message")], className="table-heading"), html.Div(id="stock-table", className="table-wrap")], className="surface activity-surface"),
            html.Footer(" is a market research demo. Data is fetched from StockAnalysis.com and is not investment advice.", className="footer"),
            dcc.Interval(id="auto-refresh", interval=DEFAULT_REFRESH_SECONDS * 1000, n_intervals=0),
            dcc.Store(id="refresh-counter", data=0),
        ], id="fishing-content"),
        inspector_layout(DEFAULT_TICKERS),
        intraday_layout(DEFAULT_TICKERS),
    ], id="main-content", className="main-content"),
], className="app-shell")


@app.callback(Output("sidebar", "className"), Input("sidebar-toggle", "n_clicks"), State("sidebar", "className"))
def toggle_sidebar(_clicks: int | None, class_name: str) -> str:
    if not _clicks:
        return class_name
    return "sidebar collapsed" if "collapsed" not in class_name else "sidebar"


@app.callback(
    Output("fishing-content", "style"),
    Output("inspector-content", "style"),
    Output("intraday-content", "style"),
    Output("sidebar-app-name", "children"),
    Output("fishing-settings", "style"),
    Output("intraday-sidebar-panel", "style"),
    Input("app-select", "value"),
)
def switch_app(app_name: str):
    inspector_active = app_name == "inspector"
    intraday_active = app_name == "intraday"
    return (
        {"display": "none"} if inspector_active or intraday_active else {},
        {} if inspector_active else {"display": "none"},
        {} if intraday_active else {"display": "none"},
        "Intraday Tape" if intraday_active else "Parabolic Inspector" if inspector_active else "Fishing",
        {"display": "none"} if inspector_active or intraday_active else {},
        {} if intraday_active else {"display": "none"},
    )


@app.callback(
    Output("inspector-ticker", "options"),
    Output("inspector-ticker", "value"),
    Output("intraday-ticker", "options"),
    Output("intraday-ticker", "value"),
    Input("inspector-tickers", "value"),
    State("inspector-ticker", "value"),
)
def update_inspector_tickers(raw_tickers: str | None, current_ticker: str | None):
    tickers = parse_tickers(raw_tickers)
    value = current_ticker if current_ticker in tickers else tickers[0]
    options = [{"label": ticker, "value": ticker} for ticker in tickers]
    return options, value, options, value


@app.callback(
    Output("inspector-status", "children"),
    Output("inspector-metrics", "children"),
    Output("inspector-chart", "figure"),
    Output("inspector-summary", "children"),
    Output("inspector-technical", "children"),
    Output("inspector-fundamentals", "children"),
    Input("inspector-analyze", "n_clicks"),
    State("inspector-ticker", "value"),
)
def update_inspector(_clicks: int | None, symbol: str):
    return render_inspector(symbol)


@app.callback(
    Output("intraday-status", "children"),
    Output("intraday-metrics", "children"),
    Output("intraday-stats", "children"),
    Output("intraday-price", "figure"),
    Output("intraday-volume", "figure"),
    Output("intraday-data", "children"),
    Input("intraday-refresh", "n_clicks"),
    Input("intraday-ticker", "value"),
)
def update_intraday(_clicks: int | None, symbol: str):
    return render_intraday(symbol, _clicks)


@app.callback(
    Output("intraday-sidebar-range", "children"),
    Input("app-select", "value"),
    Input("inspector-tickers", "value"),
    Input("intraday-refresh", "n_clicks"),
    Input("intraday-ticker", "value"),
)
def update_intraday_sidebar(app_name: str, raw_tickers: str | None, _refresh: int | None, selected_ticker: str | None):
    if app_name != "intraday":
        return []
    if _refresh is not None:
        clear_caches()
    tickers = parse_tickers(raw_tickers)
    if selected_ticker and selected_ticker not in tickers:
        tickers = [selected_ticker] + tickers
    return render_sidebar_range(tickers)


@app.callback(Output("auto-refresh", "interval"), Input("refresh-seconds", "value"))
def update_refresh_interval(seconds: int | None) -> int:
    return max(10, min(int(seconds or DEFAULT_REFRESH_SECONDS), 600)) * 1000


@app.callback(
    Output("refresh-summary", "children"), Output("table-heading", "children"), Output("status-message", "children"), Output("stock-table", "children"), Output("refresh-counter", "data"),
    Input("page-select", "value"), Input("auto-refresh", "n_intervals"), Input("manual-refresh", "n_clicks"), Input("yellow-threshold", "value"), Input("orange-threshold", "value"), Input("red-threshold", "value"), State("refresh-counter", "data"), State("refresh-seconds", "value"),
)
def update_fishing(page_name: str, _intervals: int, _manual_clicks: int | None, yellow_threshold: float | None, orange_threshold: float | None, red_threshold: float | None, refresh_counter: int | None, refresh_seconds: int | None):
    yellow = float(yellow_threshold if yellow_threshold is not None else DEFAULT_YELLOW_THRESHOLD)
    orange = max(float(orange_threshold if orange_threshold is not None else DEFAULT_ORANGE_THRESHOLD), yellow)
    red = max(float(red_threshold if red_threshold is not None else DEFAULT_RED_THRESHOLD), orange)
    frame, error = scrape_stock_top10(PAGES.get(page_name, PAGES[get_default_page()]))
    count = 0 if frame is None else len(frame)
    counter = int(refresh_counter or 0) + 1
    seconds = max(10, min(int(refresh_seconds or DEFAULT_REFRESH_SECONDS), 600))
    now = datetime.now().astimezone().strftime("%b %d, %Y at %H:%M:%S %Z")
    status = error or f"Showing {count} qualifying stocks"
    table = build_table(frame, yellow, orange, red) if frame is not None else html.Div(error, className="error-state")
    return f"{page_name} · Updated {now} · Every {seconds} sec · Refresh #{counter}", f"Top 10: {page_name}", status, table, counter


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8050)
