from __future__ import annotations

import pandas as pd
import requests
from dash import dash_table, html

# Pages mapped directly to TradingView's API scanner payloads
PAGES = {
    "Premarket Movers": "https://www.tradingview.com/markets/stocks-usa/market-movers-pre-market-gainers/",
    "Top Daily Gainers": "https://www.tradingview.com/markets/stocks-usa/market-movers-gainers/",
}

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def scrape_stock_top10(page_name: str = "Premarket Movers") -> tuple[pd.DataFrame | None, str | None]:
    """Queries TradingView's internal scanner API directly."""
    
    # Define payload queries for Premarket vs. Open Market Gainers
    if "premarket" in page_name.lower():
        payload = {
            "filter": [{"left": "premarket_change", "operation": "nempty"}],
            "options": {"active_symbols_only": True},
            "markets": ["america"],
            "symbols": {"query": {"types": []}, "tickers": []},
            "columns": ["name", "description", "premarket_close", "premarket_change", "premarket_volume"],
            "sort": {"sortBy": "premarket_change", "sortOrder": "desc"},
            "range": [0, 25]
        }
    else:  # Open Market Gainers
        payload = {
            "filter": [{"left": "change", "operation": "greater", "right": 0}],
            "options": {"active_symbols_only": True},
            "markets": ["america"],
            "symbols": {"query": {"types": []}, "tickers": []},
            "columns": ["name", "description", "close", "change", "volume"],
            "sort": {"sortBy": "change", "sortOrder": "desc"},
            "range": [0, 25]
        }

    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/",
    }

    try:
        url = "https://scanner.tradingview.com/america/scan"
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        rows = []
        for item in data.get("data", []):
            d = item.get("d", [])
            if len(d) >= 5:
                rows.append({
                    "Symbol": d[0],
                    "Name": d[1],
                    "Price": float(d[2]) if d[2] is not None else 0.0,
                    "% Change": float(d[3]) if d[3] is not None else 0.0,
                    "Volume": float(d[4]) if d[4] is not None else 0.0,
                })

        if not rows:
            return None, "No data returned from TradingView API."

        frame = pd.DataFrame(rows)

        # Apply price and volume threshold filters
        frame = frame[(frame["Price"] >= 0.80) & (frame["Volume"] >= 1_000)]

        return frame.head(10).copy(), None

    except requests.RequestException as error:
        return None, f"Could not reach TradingView: {error}"
    except (ValueError, KeyError) as error:
        return None, f"Could not parse TradingView payload: {error}"


def _change_column(frame: pd.DataFrame) -> str | None:
    return next((col for col in frame.columns if "%" in str(col) or "change" in str(col).lower()), None)


def build_table(
    frame: pd.DataFrame | None,
    yellow_threshold: float = 5.0,
    orange_threshold: float = 10.0,
    red_threshold: float = 20.0,
) -> html.Div | dash_table.DataTable:
    if frame is None or frame.empty:
        return html.Div("No stocks matched the current filters.", className="empty-state")

    change_column = _change_column(frame)
    rows = frame.copy()

    # Create clickable TradingView stock URLs
    rows["Ticker"] = rows["Symbol"].astype(str)
    rows["Ticker"] = rows["Ticker"].map(
        lambda ticker: f"[{ticker}](https://www.tradingview.com/symbols/{ticker.upper()}/)"
    )

    # Format numeric values
    rows["Price"] = rows["Price"].map(lambda v: f"${v:,.2f}")
    if change_column:
        rows["% Change"] = rows[change_column].map(lambda v: f"+{v:.2f}%" if v > 0 else f"{v:.2f}%")
    rows["Volume"] = rows["Volume"].map(lambda v: f"{v:,.0f}")

    ordered = ["Ticker", "Name", "Price", "% Change", "Volume"]
    display_cols = [c for c in ordered if c in rows.columns]

    data = rows[display_cols].to_dict("records")
    columns = [
        {"name": col, "id": col, "presentation": "markdown" if col == "Ticker" else "input"}
        for col in display_cols
    ]

    # Conditional formatting
    conditional = []
    if change_column:
        for index, row in frame.iterrows():
            try:
                value = float(row[change_column])
            except (TypeError, ValueError):
                continue

            if value >= red_threshold:
                color, text_color = "#b22222", "white"
            elif value >= orange_threshold:
                color, text_color = "#ff7f0e", "white"
            elif value >= yellow_threshold:
                color, text_color = "#f4d03f", "#17221b"
            else:
                continue

            conditional.append(
                {
                    "if": {"row_index": frame.index.get_loc(index)},
                    "backgroundColor": color,
                    "color": text_color,
                    "fontWeight": "600",
                }
            )

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
            "fontFamily": "DM Sans, sans-serif",
            "fontSize": "13px",
            "border": "0",
            "borderTop": "1px solid #26362e",
            "padding": "8px 12px",
            "textAlign": "left",
            "whiteSpace": "nowrap",
        },
        style_data_conditional=conditional,
    )
