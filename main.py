from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from dash import Dash, Input, Output, State, dcc, html

from fishing import PAGES, build_table, scrape_stock_top10

DEFAULT_REFRESH_SECONDS = 30
DEFAULT_YELLOW_THRESHOLD = 100.0
DEFAULT_GREEN_THRESHOLD = 150.0


def get_default_page() -> str:
    now = datetime.now(ZoneInfo("America/New_York"))
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=20, minute=0, second=0, microsecond=0)
    if now.weekday() < 5 and market_open <= now < market_close:
        return "Top Daily Gainers"
    return "Premarket Movers"


app = Dash(__name__, title="Market Intelligence")
server = app.server


def sidebar() -> html.Aside:
    return html.Aside([
        html.Div("MARKET INTELLIGENCE", className="eyebrow sidebar-eyebrow"),
        html.Button("☰  Settings", id="sidebar-toggle", className="sidebar-toggle"),
        html.Div([
            html.Label("APPLICATION", className="setting-label"),
            dcc.RadioItems(id="app-select", options=[{"label": "Fishing · Market tracker", "value": "fishing"}], value="fishing", className="sidebar-control sidebar-radio", inputClassName="sidebar-radio-input", labelClassName="sidebar-radio-label"),
            html.Label("MARKET VIEW", className="setting-label"),
            dcc.Dropdown(id="page-select", options=[{"label": name, "value": name} for name in PAGES], value=get_default_page(), clearable=False, className="sidebar-control"),
            html.Label("REFRESH INTERVAL", className="setting-label"),
            dcc.Input(id="refresh-seconds", type="number", min=10, max=600, step=5, value=DEFAULT_REFRESH_SECONDS, className="sidebar-input"),
            html.Span("seconds", className="setting-suffix"),
            html.Label("YELLOW THRESHOLD", className="setting-label"),
            dcc.Input(id="yellow-threshold", type="number", min=0, max=1000, step=5, value=DEFAULT_YELLOW_THRESHOLD, className="sidebar-input"),
            html.Span("% gain", className="setting-suffix"),
            html.Label("GREEN THRESHOLD", className="setting-label"),
            dcc.Input(id="green-threshold", type="number", min=0, max=1000, step=5, value=DEFAULT_GREEN_THRESHOLD, className="sidebar-input"),
            html.Span("% gain", className="setting-suffix"),
        ], id="sidebar-settings", className="sidebar-settings"),
        html.Div([html.P("ACTIVE APP", className="eyebrow"), html.P("Fishing", className="source-name"), html.P("Top market gainers with live filters", className="target-note")], className="sidebar-target"),
    ], id="sidebar", className="sidebar")


app.layout = html.Div([
    sidebar(),
    html.Main([
        html.Div([html.Div([html.H2("Fishing"), html.P("Top market gainers, surfaced at the top of the app.", className="intro-copy")]), html.Div(id="refresh-summary", className="section-caption")], className="section-header"),
        html.Section([html.Div([html.Div([html.H3(id="table-heading"), html.Span("Click a ticker to open its StockAnalysis page.", className="section-caption")], className="chart-heading"), html.Div(id="status-message", className="status-message")], className="table-heading"), html.Div(id="stock-table", className="table-wrap")], className="surface activity-surface"),
        html.Footer(" is a market research demo. Data is fetched from StockAnalysis.com and is not investment advice.", className="footer"),
        dcc.Interval(id="auto-refresh", interval=DEFAULT_REFRESH_SECONDS * 1000, n_intervals=0),
        dcc.Store(id="refresh-counter", data=0),
    ], id="main-content", className="main-content"),
], className="app-shell")


@app.callback(Output("sidebar", "className"), Input("sidebar-toggle", "n_clicks"), State("sidebar", "className"))
def toggle_sidebar(_clicks: int | None, class_name: str) -> str:
    if not _clicks:
        return class_name
    return "sidebar collapsed" if "collapsed" not in class_name else "sidebar"


@app.callback(Output("auto-refresh", "interval"), Input("refresh-seconds", "value"))
def update_refresh_interval(seconds: int | None) -> int:
    return max(10, min(int(seconds or DEFAULT_REFRESH_SECONDS), 600)) * 1000


@app.callback(
    Output("refresh-summary", "children"), Output("table-heading", "children"), Output("status-message", "children"), Output("stock-table", "children"), Output("refresh-counter", "data"),
    Input("page-select", "value"), Input("auto-refresh", "n_intervals"), Input("manual-refresh", "n_clicks"), Input("yellow-threshold", "value"), Input("green-threshold", "value"), State("refresh-counter", "data"), State("refresh-seconds", "value"),
)
def update_fishing(page_name: str, _intervals: int, _manual_clicks: int | None, yellow_threshold: float | None, green_threshold: float | None, refresh_counter: int | None, refresh_seconds: int | None):
    yellow = float(yellow_threshold if yellow_threshold is not None else DEFAULT_YELLOW_THRESHOLD)
    green = max(float(green_threshold if green_threshold is not None else DEFAULT_GREEN_THRESHOLD), yellow)
    frame, error = scrape_stock_top10(PAGES.get(page_name, PAGES[get_default_page()]))
    count = 0 if frame is None else len(frame)
    counter = int(refresh_counter or 0) + 1
    seconds = max(10, min(int(refresh_seconds or DEFAULT_REFRESH_SECONDS), 600))
    now = datetime.now().astimezone().strftime("%b %d, %Y at %H:%M:%S %Z")
    status = error or f"Showing {count} qualifying stocks"
    table = build_table(frame, yellow, green) if frame is not None else html.Div(error, className="error-state")
    return f"{page_name} · Updated {now} · Every {seconds} sec · Refresh #{counter}", f"Top 10: {page_name}", status, table, counter


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8050)
