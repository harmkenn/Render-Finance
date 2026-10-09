from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import zoneinfo

from bs4 import BeautifulSoup
import dash
from dash import dash_table, dcc, html, Input, Output
import pandas as pd
import requests

PAGES = {
    "Premarket Movers": "https://stockanalysis.com/markets/premarket/",
    "Top Daily Gainers": "https://stockanalysis.com/markets/gainers/",
}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"


def get_active_market_url() -> str:
    """Determines whether to use Premarket or Regular Market gainers based on US Eastern Time."""
    eastern = zoneinfo.ZoneInfo("America/New_York")
    now = datetime.now(eastern)

    # Weekdays: Monday (0) through Friday (4)
    if now.weekday() < 5:
        premarket_start = now.replace(hour=4, minute=0, second=0, microsecond=0)
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)

        # 4:00 AM ET to 9:30 AM ET on weekdays -> Premarket
        if premarket_start <= now < market_open:
            return PAGES["Premarket Movers"]

    # Default to Regular/Top Gainers (Market Open, After Hours, and Weekends)
    return PAGES["Top Daily Gainers"]


def fetch_nasdaq_price(symbol: str) -> str:
    """Queries Nasdaq's JSON API directly for the live price of a given ticker symbol."""
    clean_symbol = str(symbol).strip().lower()
    url = f"https://api.nasdaq.com/api/quote/{clean_symbol}/info?assetclass=stocks"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.nasdaq.com",
        "Referer": f"https://www.nasdaq.com/market-activity/stocks/{clean_symbol}",
    }
    try:
        response = requests.get(url, headers=headers, timeout=4)
        if response.status_code == 200:
            data = response.json()
            primary_data = data.get("data", {}).get("primaryData", {})
            last_price = primary_data.get("lastSalePrice")
            if last_price:
                return last_price
    except Exception:
        pass
    return "N/A"


def fetch_nasdaq_prices_parallel(symbols: list[str]) -> list[str]:
    """Fetches prices for multiple tickers concurrently to keep response times fast."""
    with ThreadPoolExecutor(max_workers=10) as executor:
        return list(executor.map(fetch_nasdaq_price, symbols))


def parse_price(value: object) -> float:
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def parse_volume(value: object) -> float:
    try:
        clean_value = str(value).replace(",", "").strip().upper()
        multiplier = 1
        for suffix, factor in (("K", 1_000), ("M", 1_000_000), ("B", 1_000_000_000)):
            if clean_value.endswith(suffix):
                multiplier, clean_value = factor, clean_value[:-1]
                break
        return float(clean_value) * multiplier
    except (TypeError, ValueError):
        return 0.0


def scrape_stock_top10(target: str | None = None) -> tuple[pd.DataFrame | None, str | None]:
    """Scrapes stock data with flexible market routing and schema mapping."""
    if not target or str(target).strip().lower() in {"auto", "none"}:
        url = get_active_market_url()
    elif target in PAGES:
        url = PAGES[target]
    else:
        url = str(target)

    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
        response.raise_for_status()
        table = BeautifulSoup(response.text, "html.parser").find("table")
        if table is None:
            return None, "The source page did not contain a market table."

        headers = [header.get_text(strip=True) for header in table.find_all("th")]
        rows = []
        for table_row in table.find_all("tr")[1:30]:
            cells = [cell.get_text(" ", strip=True) for cell in table_row.find_all("td")]
            if cells:
                rows.append(cells)

        if not rows:
            return None, "No market rows were returned by the source page."

        frame = pd.DataFrame(rows, columns=headers if headers and len(headers) == len(rows[0]) else None)

        symbol_column = next((c for c in frame.columns if "symbol" in str(c).lower() or "ticker" in str(c).lower()), frame.columns[0])
        price_column = next((c for c in frame.columns if "price" in str(c).lower()), None)
        volume_column = next((c for c in frame.columns if "volume" in str(c).lower()), None)

        if price_column:
            frame = frame[frame[price_column].map(parse_price) >= 0.80]
        if volume_column:
            frame = frame[frame[volume_column].map(parse_volume) >= 1_000]

        top_frame = frame.head(10).copy()
        if top_frame.empty:
            return None, "No stocks matched the price/volume filters."

        top_frame["Nasdaq Quote"] = top_frame[symbol_column].astype(str).map(
            lambda ticker: f"https://www.nasdaq.com/market-activity/stocks/{ticker.lower()}"
        )

        tickers = top_frame[symbol_column].astype(str).tolist()
        top_frame["Nasdaq Price"] = fetch_nasdaq_prices_parallel(tickers)

        cols = list(top_frame.columns)
        if price_column and price_column in cols:
            price_idx = cols.index(price_column)
            cols.remove("Nasdaq Price")
            cols.remove("Nasdaq Quote")
            cols.insert(price_idx + 1, "Nasdaq Price")
            cols.insert(price_idx + 2, "Nasdaq Quote")
            top_frame = top_frame[cols]

        return top_frame, None
    except requests.RequestException as error:
        return None, f"Could not reach StockAnalysis: {error}"
    except (ValueError, IndexError) as error:
        return None, f"Could not read the market table: {error}"


def _change_column(frame: pd.DataFrame) -> str | None:
    return next((str(col) for col in frame.columns if "%" in str(col) or "change" in str(col).lower()), None)


def build_table(
    frame: pd.DataFrame | None,
    yellow_threshold: float = 10.0,
    orange_threshold: float = 20.0,
    red_threshold: float = 30.0,
) -> html.Div | dash_table.DataTable:
    if frame is None or frame.empty:
        return html.Div("No stocks matched the current filters.", className="empty-state")

    symbol_column = next((c for c in frame.columns if "symbol" in str(c).lower() or "ticker" in str(c).lower()), frame.columns[0])
    change_column = _change_column(frame)
    rows = frame.copy()

    rows["Ticker Raw"] = rows[symbol_column].astype(str)
    rows["Ticker"] = rows["Ticker Raw"].map(lambda t: f"[{t}](https://stockanalysis.com/stocks/{t.lower()}/)")

    if "Nasdaq Quote" in rows.columns:
        rows["Nasdaq Link"] = rows["Nasdaq Quote"].map(lambda url: f"[Nasdaq Quote]({url})")
        rows = rows.drop(columns=["Nasdaq Quote"])

    rows = rows.drop(columns=[symbol_column, "Ticker Raw"], errors="ignore")

    market_cap_column = next((c for c in rows.columns if "market cap" in str(c).lower()), None)
    if market_cap_column:
        rows = rows.drop(columns=[market_cap_column])

    ordered = ["Ticker"] + [c for c in rows.columns if c not in {"Ticker", "Ticker URL"}]
    data = rows[ordered].to_dict("records")
    columns = [{"name": c, "id": c} for c in ordered]

    for col in columns:
        if col["id"] in {"Ticker", "Nasdaq Link"}:
            col["presentation"] = "markdown"

    conditional = []
    if change_column:
        for idx, (_, row) in enumerate(frame.iterrows()):
            try:
                val = float(str(row[change_column]).replace("%", "").replace("+", "").replace(",", "").strip())
            except (TypeError, ValueError):
                continue

            if val >= red_threshold:
                color, text_color = "#b22222", "white"
            elif val >= orange_threshold:
                color, text_color = "#ff7f0e", "white"
            elif val >= yellow_threshold:
                color, text_color = "#f4d03f", "#17221b"
            else:
                continue

            conditional.append({
                "if": {"row_index": idx},
                "backgroundColor": color,
                "color": text_color,
                "fontWeight": "600",
            })

    return dash_table.DataTable(
        data=data,
        columns=columns,
        markdown_options={"link_target": "_blank"},
        sort_action="native",
        page_action="none",
        style_as_list_view=True,
        style_table={"overflowX": "auto"},
        style_header={
            "backgroundColor": "#202f27",
            "color": "#91a39a",
            "fontWeight": "700",
            "fontSize": "11px",
            "textTransform": "uppercase",
            "letterSpacing": "1px",
            "border": "0",
            "padding": "14px 12px",
        },
        style_cell={
            "backgroundColor": "#17221d",
            "color": "#e8f1eb",
            "fontFamily": "DM Sans",
            "fontSize": "13px",
            "border": "0",
            "borderTop": "1px solid #26362e",
            "padding": "8px 12px",
            "textAlign": "left",
            "whiteSpace": "nowrap",
        },
        style_data_conditional=conditional,
    )


# --- DASH APP BOOTSTRAP ---
app = dash.Dash(__name__)

app.layout = html.Div([
    html.H2("Live Market Top Movers", style={"color": "#e8f1eb", "fontFamily": "DM Sans"}),
    
    html.Div([
        html.Label("Select Market View: ", style={"color": "#91a39a", "marginRight": "10px"}),
        dcc.Dropdown(
            id="market-target-dropdown",
            options=[
                {"label": "Auto (Time Based)", "value": "Auto
