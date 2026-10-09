from __future__ import annotations

from datetime import datetime
import zoneinfo

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dash import dash_table, html

PAGES = {
    "Premarket Movers": "https://stockanalysis.com/markets/premarket/",
    "Top Daily Gainers": "https://stockanalysis.com/markets/gainers/",
}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"


def get_active_market_url() -> str:
    """
    Determines whether to use Premarket or Regular Market gainers based on current US Eastern Time.
    Returns the target URL string.
    """
    eastern = zoneinfo.ZoneInfo("America/New_York")
    now = datetime.now(eastern)

    # Check if weekday (0 = Monday, 4 = Friday)
    if now.weekday() < 5:
        premarket_start = now.replace(hour=4, minute=0, second=0, microsecond=0)
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)

        # 4:00 AM ET to 9:30 AM ET on weekdays -> Premarket
        if premarket_start <= now < market_open:
            return PAGES["Premarket Movers"]

    # Default to Regular/Top Gainers (Market Open, After Hours, and Weekends)
    return PAGES["Top Daily Gainers"]


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
    """
    Scrapes stock data. Accepts either a URL or a key from PAGES (e.g., 'Premarket Movers').
    If target is None or 'Auto', automatically selects the URL based on market hours.
    Returns (DataFrame | None, ErrorMessage | None).
    """
    if not target or target.lower() == "auto":
        url = get_active_market_url()
    elif target in PAGES:
        url = PAGES[target]
    else:
        url = target  # Assume direct URL string was passed

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

        symbol_column = next((column for column in frame.columns if "symbol" in str(column).lower() or "ticker" in str(column).lower()), frame.columns[0])
        price_column = next((column for column in frame.columns if "price" in str(column).lower()), None)
        volume_column = next((column for column in frame.columns if "volume" in str(column).lower()), None)

        if price_column:
            frame = frame[frame[price_column].map(parse_price) >= 0.80]
        if volume_column:
            frame = frame[frame[volume_column].map(parse_volume) >= 1_000]

        top_frame = frame.head(10).copy()

        # Build Nasdaq URL column next to price
        top_frame["Nasdaq Quote"] = top_frame[symbol_column].astype(str).map(
            lambda ticker: f"https://www.nasdaq.com/market-activity/stocks/{ticker.lower()}"
        )

        cols = list(top_frame.columns)
        if price_column and price_column in cols:
            price_idx = cols.index(price_column)
            cols.remove("Nasdaq Quote")
            cols.insert(price_idx + 1, "Nasdaq Quote")
            top_frame = top_frame[cols]

        return top_frame, None
    except requests.RequestException as error:
        return None, f"Could not reach StockAnalysis: {error}"
    except (ValueError, IndexError) as error:
        return None, f"Could not read the market table: {error}"


def _change_column(frame: pd.DataFrame) -> object | None:
    return next((column for column in frame.columns if "%" in str(column) or "change" in str(column).lower()), None)


def build_table(frame: pd.DataFrame | None, yellow_threshold: float, orange_threshold: float, red_threshold: float) -> html.Div | dash_table.DataTable:
    if frame is None or frame.empty:
        return html.Div("No stocks matched the current filters.", className="empty-state")

    symbol_column = next((column for column in frame.columns if "symbol" in str(column).lower() or "ticker" in str(column).lower()), frame.columns[0])
    change_column = _change_column(frame)
    rows = frame.copy()

    # Configure StockAnalysis Ticker link
    rows["Ticker"] = rows[symbol_column].astype(str)
    rows["Ticker URL"] = rows["Ticker"].map(lambda ticker: f"https://stockanalysis.com/stocks/{ticker.lower()}/")

    # Configure Nasdaq Link column
    if "Nasdaq Quote" in rows.columns:
        rows["Nasdaq Link"] = rows.apply(lambda r: f"[Nasdaq Quote]({r['Nasdaq Quote']})", axis=1)
        rows = rows.drop(columns=["Nasdaq Quote"])

    rows = rows.drop(columns=[symbol_column])
    market_cap_column = next((column for column in rows.columns if "market cap" in str(column).lower()), None)
    if market_cap_column:
        rows = rows.drop(columns=[market_cap_column])

    ordered = ["Ticker"] + [column for column in rows.columns if column not in {"Ticker", "Ticker URL"}]
    data = rows[ordered].to_dict("records")

    for row in data:
        ticker = row["Ticker"]
        row["Ticker"] = f"[{ticker}]({rows.loc[rows['Ticker'] == ticker, 'Ticker URL'].iloc[0]})"

    columns = [{"name": column, "id": column} for column in ordered]

    # Enable markdown presentation for Ticker and Nasdaq Link columns
    for col in columns:
        if col["id"] in {"Ticker", "Nasdaq Link"}:
            col["presentation"] = "markdown"

    conditional = []
    if change_column:
        for index, row in frame.iterrows():
            try:
                value = float(str(row[change_column]).replace("%", "").replace("+", "").replace(",", "").strip())
            except (TypeError, ValueError):
                continue
            if value >= red_threshold:
                color = "#b22222"
                text_color = "white"
            elif value >= orange_threshold:
                color = "#ff7f0e"
                text_color = "white"
            elif value >= yellow_threshold:
                color = "#f4d03f"
                text_color = "#17221b"
            else:
                continue
            conditional.append({"if": {"row_index": frame.index.get_loc(index)}, "backgroundColor": color, "color": text_color, "fontWeight": "600"})

    return dash_table.DataTable(
        data=data,
        columns=columns,
        markdown_options={"link_target": "_blank"},
        sort_action="native",
        page_action="none",
        style_as_list_view=True,
        style_table={"overflowX": "auto"},
        style_header={"backgroundColor": "#202f27", "color": "#91a39a", "fontWeight": "700", "fontSize": "11px", "textTransform": "uppercase", "letterSpacing": "1px", "border": "0", "padding": "14px 12px"},
        style_cell={"backgroundColor": "#17221d", "color": "#e8f1eb", "fontFamily": "DM Sans", "fontSize": "13px", "border": "0", "borderTop": "1px solid #26362e", "padding": "8px 12px", "textAlign": "left", "whiteSpace": "nowrap"},
        style_data_conditional=conditional,
    )
