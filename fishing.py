from __future__ import annotations

import time
import pandas as pd
import requests
from dash import dash_table, html

# Pages mapped directly to StockAnalysis internal JSON endpoints
PAGES = {
    "Premarket Movers": "https://stockanalysis.com/api/screener/s/f?m=premarketGainers&s=volume-desc",
    "Top Daily Gainers": "https://stockanalysis.com/api/screener/s/f?m=gainers&s=volume-desc",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def fetch_stock_top10(target_url_or_key: str) -> tuple[pd.DataFrame | None, str | None]:
    """Fetches real-time stock data directly from JSON endpoints."""
    # Resolve page name key to URL if passed as key
    api_url = PAGES.get(target_url_or_key, target_url_or_key)

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
    }

    try:
        # Append microsecond timestamp parameter for cache busting
        cache_buster_url = f"{api_url}&_t={int(time.time() * 1000)}"
        response = requests.get(cache_buster_url, headers=headers, timeout=10)
        response.raise_for_status()

        payload = response.json()
        raw_rows = payload.get("data", {}).get("data", [])

        if not raw_rows:
            return None, "No market data returned from the source API."

        frame = pd.DataFrame(raw_rows)

        if "s" not in frame.columns:
            return None, "Unexpected data format received from API."

        frame = frame.rename(columns={"s": "symbol", "n": "name"})

        if "price" in frame.columns:
            frame["price"] = pd.to_numeric(frame["price"], errors="coerce").fillna(0.0)
            frame = frame[frame["price"] >= 0.80]

        if "volume" in frame.columns:
            frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").fillna(0)
            frame = frame[frame["volume"] >= 1_000]

        return frame.head(10).copy(), None

    except requests.RequestException as error:
        return None, f"Could not reach StockAnalysis API: {error}"
    except (ValueError, KeyError) as error:
        return None, f"Could not parse market response: {error}"


# Alias for backward compatibility with existing codebase
scrape_stock_top10 = fetch_stock_top10


def build_table(
    frame: pd.DataFrame | None,
    yellow_threshold: float = 5.0,
    orange_threshold: float = 10.0,
    red_threshold: float = 20.0,
) -> html.Div | dash_table.DataTable:
    if frame is None or frame.empty:
        return html.Div("No stocks matched the current filters.", className="empty-state")

    change_column = next(
        (col for col in ["change", "chg", "changePercent"] if col in frame.columns), None
    )

    rows = frame.copy()
    rows["Ticker"] = rows["symbol"].astype(str)
    rows["Ticker"] = rows["Ticker"].map(
        lambda t: f"[{t}](https://stockanalysis.com/stocks/{t.lower()}/)"
    )

    if "price" in rows.columns:
        rows["Price"] = rows["price"].map(lambda val: f"${val:,.2f}")
    if change_column:
        rows["% Change"] = rows[change_column].map(
            lambda val: f"+{val:.2f}%" if val > 0 else f"{val:.2f}%"
        )
    if "volume" in rows.columns:
        rows["Volume"] = rows["volume"].map(lambda val: f"{val:,.0f}")

    desired_order = ["Ticker", "name", "Price", "% Change", "Volume"]
    display_columns = [col for col in desired_order if col in rows.columns]

    data = rows[display_columns].to_dict("records")
    columns = [
        {
            "name": col.replace("name", "Company Name"),
            "id": col,
            "presentation": "markdown" if col == "Ticker" else "input",
        }
        for col in display_columns
    ]

    conditional = []
    if change_column:
        for idx, row in frame.iterrows():
            try:
                val = float(row[change_column])
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

            conditional.append(
                {
                    "if": {"row_index": frame.index.get_loc(idx)},
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
