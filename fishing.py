from __future__ import annotations

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dash import dash_table, html

PAGES = {
    "Premarket Movers": "https://stockanalysis.com/markets/premarket/",
    "Top Daily Gainers": "https://stockanalysis.com/markets/gainers/",
}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"


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
        volume_column = next((column for column in frame.columns if "volume" in str(column).lower()), None)
        if price_column:
            frame = frame[frame[price_column].map(parse_price) >= 0.80]
        if volume_column:
            frame = frame[frame[volume_column].map(parse_volume) >= 1_000]
        return frame.head(10).copy(), None
    except requests.RequestException as error:
        return None, f"Could not reach StockAnalysis: {error}"
    except (ValueError, IndexError) as error:
        return None, f"Could not read the market table: {error}"


def _change_column(frame: pd.DataFrame) -> object | None:
    return next((column for column in frame.columns if "%" in str(column) or "change" in str(column).lower()), None)


def build_table(frame: pd.DataFrame | None, yellow_threshold: float, green_threshold: float) -> html.Div | dash_table.DataTable:
    if frame is None or frame.empty:
        return html.Div("No stocks matched the current filters.", className="empty-state")
    symbol_column = next((column for column in frame.columns if "symbol" in str(column).lower() or "ticker" in str(column).lower()), frame.columns[0])
    change_column = _change_column(frame)
    rows = frame.copy()
    rows["Ticker"] = rows[symbol_column].astype(str)
    rows["Ticker URL"] = rows["Ticker"].map(lambda ticker: f"https://stockanalysis.com/stocks/{ticker.lower()}/")
    rows = rows.drop(columns=[symbol_column])
    ordered = ["Ticker"] + [column for column in rows.columns if column not in {"Ticker", "Ticker URL"}]
    data = rows[ordered].to_dict("records")
    for row in data:
        ticker = row["Ticker"]
        row["Ticker"] = f"[{ticker}]({rows.loc[rows['Ticker'] == ticker, 'Ticker URL'].iloc[0]})"
    columns = [{"name": column, "id": column} for column in ordered]
    columns[0]["presentation"] = "markdown"
    conditional = []
    if change_column:
        for index, row in frame.iterrows():
            try:
                value = float(str(row[change_column]).replace("%", "").replace("+", "").replace(",", "").strip())
            except (TypeError, ValueError):
                continue
            color = "#23513e" if value >= green_threshold else "#f4d03f" if value >= yellow_threshold else None
            if color:
                conditional.append({"if": {"row_index": frame.index.get_loc(index)}, "backgroundColor": color, "color": "white" if color == "#23513e" else "#17221b", "fontWeight": "600"})
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
