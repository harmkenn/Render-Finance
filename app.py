from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dash import Dash, Input, Output, State, dash_table, dcc, html


PAGES = {
    "Premarket Movers": "https://stockanalysis.com/markets/premarket/",
    "Top Daily Gainers": "https://stockanalysis.com/markets/gainers/",
}
DEFAULT_REFRESH_SECONDS = 30
DEFAULT_YELLOW_THRESHOLD = 100.0
DEFAULT_GREEN_THRESHOLD = 150.0
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"


def get_default_page() -> str:
    now = datetime.now(ZoneInfo("America/New_York"))
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=20, minute=0, second=0, microsecond=0)
    if now.weekday() < 5 and market_open <= now < market_close:
        return "Top Daily Gainers"
    return "Premarket Movers"


def parse_price(value: object) -> float:
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def parse_volume(value: object) -> float:
    try:
        clean_value = str(value).replace(",", "").strip().upper()
        multiplier = 1
        if clean_value.endswith("K"):
            multiplier, clean_value = 1_000, clean_value[:-1]
        elif clean_value.endswith("M"):
            multiplier, clean_value = 1_000_000, clean_value[:-1]
        elif clean_value.endswith("B"):
            multiplier, clean_value = 1_000_000_000, clean_value[:-1]
        return float(clean_value) * multiplier
    except (TypeError, ValueError):
        return 0.0


def scrape_stock_top10(url: str) -> tuple[pd.DataFrame | None, str | None]:
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
        response.raise_for_status()
        table = BeautifulSoup(response.text, "html.parser").find("table")
        if table is None:
            return None, "The source page did not contain a market table."

        headers = [header.get_text(strip=True) for header in table.find_all("th")]
        rows = []
        for table_row in table.find_all("tr")[1:25]:
            cells = [cell.get_text(" ", strip=True) for cell in table_row.find_all("td")]
            if cells:
                rows.append(cells)
        if not rows:
            return None, "No market rows were returned by the source page."

        frame = pd.DataFrame(rows, columns=headers if headers and len(headers) == len(rows[0]) else None)
        price_column = next((column for column in frame.columns if "price" in str(column).lower()), None)
        if price_column:
            frame = frame[frame[price_column].map(parse_price) >= 0.80].copy()
        volume_column = next((column for column in frame.columns if "volume" in str(column).lower()), None)
        if volume_column:
            frame = frame[frame[volume_column].map(parse_volume) >= 1_000].copy()
        return frame.head(10), None
    except requests.RequestException as error:
        return None, f"Could not reach StockAnalysis: {error}"
    except (ValueError, IndexError) as error:
        return None, f"Could not read the market table: {error}"


def prepare_rows(frame: pd.DataFrame) -> tuple[list[dict], list[dict], str | None]:
    symbol_column = next((column for column in frame.columns if "symbol" in str(column).lower() or "ticker" in str(column).lower()), frame.columns[0])
    change_column = next((column for column in frame.columns if "%" in str(column) or "change" in str(column).lower()), None)
    rows = frame.copy()
    rows["Ticker"] = rows[symbol_column].astype(str)
    rows["Ticker URL"] = rows["Ticker"].map(lambda ticker: f"https://stockanalysis.com/stocks/{ticker.lower()}/")
    rows = rows.drop(columns=[symbol_column])
    ordered_columns = ["Ticker"] + [column for column in rows.columns if column not in {"Ticker", "Ticker URL"}] + ["Ticker URL"]
    rows = rows[ordered_columns]
    columns = [{"name": column, "id": column} for column in rows.columns if column != "Ticker URL"]
    columns[0] = {"name": "Ticker", "id": "Ticker", "presentation": "markdown"}
    data = rows.to_dict("records")
    for row in data:
        ticker = row["Ticker"]
        row["Ticker"] = f"[{ticker}]({row['Ticker URL']})"
    return data, columns, change_column


def build_table(frame: pd.DataFrame | None, yellow_threshold: float, green_threshold: float) -> html.Div | dash_table.DataTable:
    if frame is None or frame.empty:
        return html.Div("No stocks matched the current filters.", className="empty-state")
    data, columns, change_column = prepare_rows(frame)
    conditional = []
    if change_column:
        for row in frame.to_dict("records"):
            value_text = str(row.get(change_column, "")).replace("%", "").replace("+", "").replace(",", "").strip()
            try:
                value = float(value_text)
            except ValueError:
                continue
            if value >= green_threshold:
                conditional.append({"if": {"filter_query": f'{{{change_column}}} = "{row[change_column]}"'}, "backgroundColor": "#23513e", "color": "white", "fontWeight": "600"})
            elif value >= yellow_threshold:
                conditional.append({"if": {"filter_query": f'{{{change_column}}} = "{row[change_column]}"'}, "backgroundColor": "#f4d03f", "color": "#17221b", "fontWeight": "600"})
    return dash_table.DataTable(
        data=data,
        columns=columns,
        markdown_options={"link_target": "_blank"},
        sort_action="native",
        page_action="none",
        style_as_list_view=True,
        style_table={"overflowX": "auto"},
        style_header={"backgroundColor": "#f0f4ef", "color": "#718078", "fontWeight": "700", "fontSize": "11px", "textTransform": "uppercase", "letterSpacing": "1px", "border": "0", "padding": "14px 12px"},
        style_cell={"backgroundColor": "white", "color": "#17221b", "fontFamily": "DM Sans", "fontSize": "13px", "border": "0", "borderTop": "1px solid #edf1ed", "padding": "15px 12px", "textAlign": "left", "whiteSpace": "nowrap"},
        style_data_conditional=conditional,
    )


app = Dash(__name__, title="Luma Market Tracker")
server = app.server

app.layout = html.Div(
    [
        html.Aside(
            [
                html.Div([html.Div("L", className="brand-mark"), html.Span("luma", className="brand-name")], className="brand"),
                html.Div("MARKET INTELLIGENCE", className="eyebrow sidebar-eyebrow"),
                html.Nav([html.Div([html.Span("⌁", className="nav-icon"), "Market tracker"], className="nav-item active"), html.Div([html.Span("◌", className="nav-icon"), "Watchlists"], className="nav-item muted-nav")], className="nav-list"),
                html.Div([html.P("DATA SOURCE", className="eyebrow"), html.P("StockAnalysis.com", className="source-name"), html.P("Live market tables with local filtering", className="target-note")], className="sidebar-target"),
                html.Div([html.Div("JD", className="avatar"), html.Div([html.Strong("Jordan Davis"), html.Small("Research desk")])], className="profile"),
            ],
            className="sidebar",
        ),
        html.Main(
            [
                html.Header([html.Div([html.P("LIVE MARKET MONITOR", className="eyebrow"), html.H1("Stock analysis, in focus.")]), html.Div([html.Span("● Live", className="live-status"), html.Button("↻ Refresh now", id="manual-refresh", className="add-button")], className="header-actions")], className="topbar"),
                html.Div([html.Div([html.P("TRACKING NOW", className="eyebrow balance-label"), html.Div(id="view-title", className="balance-value"), html.Div(id="last-updated", className="balance-note")], className="balance-panel"), html.Div([html.P("FILTERED RESULTS", className="eyebrow"), html.Div(id="result-count", className="income-value"), html.Div("Top 10 after price and volume checks", className="balance-note")], className="income-panel"), html.Div([html.P("AUTO-REFRESH", className="eyebrow"), html.Div(id="refresh-summary", className="income-value"), html.Div(id="refresh-count", className="balance-note")], className="income-panel")], className="hero-grid"),
                html.Div([html.Div([html.H2("Market view"), html.P("Choose a live market table to scan for momentum.", className="intro-copy")]), html.Div([dcc.Dropdown(id="page-select", options=[{"label": name, "value": name} for name in PAGES], value=get_default_page(), clearable=False, className="filter"), dcc.Input(id="refresh-seconds", type="number", min=10, max=600, step=5, value=DEFAULT_REFRESH_SECONDS, className="number-filter", debounce=True, placeholder="Seconds"), html.Span("sec", className="input-suffix")], className="controls-row")], className="section-header"),
                html.Div([html.Div([html.P("YELLOW AT", className="metric-label"), dcc.Input(id="yellow-threshold", type="number", min=0, max=1000, step=5, value=DEFAULT_YELLOW_THRESHOLD, className="threshold-input"), html.Span("% gain", className="metric-hint")], className="metric-card compact-card"), html.Div([html.P("GREEN AT", className="metric-label"), dcc.Input(id="green-threshold", type="number", min=0, max=1000, step=5, value=DEFAULT_GREEN_THRESHOLD, className="threshold-input"), html.Span("% gain", className="metric-hint")], className="metric-card compact-card"), html.Div([html.P("MINIMUM PRICE", className="metric-label"), html.Div("$0.80", className="threshold-display"), html.Span("Applied automatically", className="metric-hint")], className="metric-card compact-card"), html.Div([html.P("MINIMUM VOLUME", className="metric-label"), html.Div("1,000", className="threshold-display"), html.Span("Shares or equivalent", className="metric-hint")], className="metric-card compact-card")], className="metric-grid four-up"),
                html.Section([html.Div([html.Div([html.H3(id="table-heading"), html.Span("Click a ticker to open its StockAnalysis page.", className="section-caption")], className="chart-heading"), html.Div(id="status-message", className="status-message")], className="table-heading"), html.Div(id="stock-table", className="table-wrap")], className="surface activity-surface"),
                html.Footer("Luma is a market research demo. Data is fetched from StockAnalysis.com and is not investment advice.", className="footer"),
                dcc.Interval(id="auto-refresh", interval=DEFAULT_REFRESH_SECONDS * 1000, n_intervals=0),
                dcc.Store(id="refresh-counter", data=0),
            ],
            className="main-content",
        ),
    ],
    className="app-shell",
)


@app.callback(Output("auto-refresh", "interval"), Input("refresh-seconds", "value"))
def update_refresh_interval(seconds: int | None) -> int:
    return max(10, min(int(seconds or DEFAULT_REFRESH_SECONDS), 600)) * 1000


@app.callback(
    Output("view-title", "children"), Output("last-updated", "children"), Output("result-count", "children"), Output("refresh-summary", "children"), Output("refresh-count", "children"), Output("table-heading", "children"), Output("status-message", "children"), Output("stock-table", "children"), Output("refresh-counter", "data"),
    Input("page-select", "value"), Input("auto-refresh", "n_intervals"), Input("manual-refresh", "n_clicks"), Input("yellow-threshold", "value"), Input("green-threshold", "value"), State("refresh-counter", "data"), State("refresh-seconds", "value"),
)
def update_market_view(page_name: str, _intervals: int, _manual_clicks: int | None, yellow_threshold: float | None, green_threshold: float | None, refresh_counter: int | None, refresh_seconds: int | None):
    yellow = float(yellow_threshold if yellow_threshold is not None else DEFAULT_YELLOW_THRESHOLD)
    green = max(float(green_threshold if green_threshold is not None else DEFAULT_GREEN_THRESHOLD), yellow)
    frame, error = scrape_stock_top10(PAGES.get(page_name, PAGES[get_default_page()]))
    count = 0 if frame is None else len(frame)
    counter = int(refresh_counter or 0) + 1
    now = datetime.now().astimezone().strftime("%b %d, %Y at %H:%M:%S %Z")
    status = error or f"Showing {count} qualifying stocks"
    table = build_table(frame, yellow, green) if frame is not None else html.Div(error, className="error-state")
    seconds = max(10, min(int(refresh_seconds or DEFAULT_REFRESH_SECONDS), 600))
    return page_name, f"Updated {now}", str(count), f"Every {seconds} sec", f"Refresh #{counter}", f"Top 10: {page_name}", status, table, counter


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
