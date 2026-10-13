from __future__ import annotations

import time
import dash
import pandas as pd
import requests
from dash import Input, Output, dcc, dash_table, html

# Internal API endpoints for StockAnalysis market screeners
PAGES = {
    "Premarket Movers": "https://stockanalysis.com/api/screener/s/f?m=premarketGainers&s=volume-desc",
    "Top Daily Gainers": "https://stockanalysis.com/api/screener/s/f?m=gainers&s=volume-desc",
}
API_ENDPOINTS = {
    "Premarket Movers": "https://stockanalysis.com/api/screener/s/f?m=premarketGainers&s=volume-desc",
    "Top Daily Gainers": "https://stockanalysis.com/api/screener/s/f?m=gainers&s=volume-desc",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def fetch_stock_top10(api_url: str) -> tuple[pd.DataFrame | None, str | None]:
    """Fetches real-time stock data directly from internal JSON API endpoints."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
    }

    try:
        # Append a microsecond timestamp parameter to force cache busting
        cache_buster_url = f"{api_url}&_t={int(time.time() * 1000)}"
        response = requests.get(cache_buster_url, headers=headers, timeout=10)
        response.raise_for_status()

        payload = response.json()
        raw_rows = payload.get("data", {}).get("data", [])

        if not raw_rows:
            return None, "No market data returned from the source API."

        # Raw JSON data into DataFrame
        frame = pd.DataFrame(raw_rows)

        # Ensure required columns exist
        if "s" not in frame.columns:
            return None, "Unexpected data format received from API."

        # Standardize column naming and missing optional fields
        frame = frame.rename(columns={"s": "symbol", "n": "name"})

        # Apply price and volume threshold filters
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


def build_table(
    frame: pd.DataFrame | None,
    yellow_threshold: float = 5.0,
    orange_threshold: float = 10.0,
    red_threshold: float = 20.0,
) -> html.Div | dash_table.DataTable:
    if frame is None or frame.empty:
        return html.Div("No stocks matched the current filters.", className="empty-state")

    # Pick dynamic percentage change column ('change' or 'chg')
    change_column = next(
        (col for col in ["change", "chg", "changePercent"] if col in frame.columns), None
    )

    rows = frame.copy()

    # Format Ticker with Markdown links
    rows["Ticker"] = rows["symbol"].astype(str)
    rows["Ticker"] = rows["Ticker"].map(
        lambda t: f"[{t}](https://stockanalysis.com/stocks/{t.lower()}/)"
    )

    # Format numeric displays cleanly for Dash UI
    if "price" in rows.columns:
        rows["Price"] = rows["price"].map(lambda val: f"${val:,.2f}")
    if change_column:
        rows["% Change"] = rows[change_column].map(
            lambda val: f"+{val:.2f}%" if val > 0 else f"{val:.2f}%"
        )
    if "volume" in rows.columns:
        rows["Volume"] = rows["volume"].map(lambda val: f"{val:,.0f}")

    # Column ordering for presentation
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

    # Dynamic row highlighting based on change percentage
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


# ----------------------------------------------------------------------
# DASH APPLICATION LAYOUT & CALLBACKS
# ----------------------------------------------------------------------

app = dash.Dash(__name__)

app.layout = html.Div(
    [
        html.H1("Live Market Movers", style={"fontFamily": "DM Sans, sans-serif", "color": "#e8f1eb"}),
        
        # Dropdown to toggle market sources dynamically
        dcc.Dropdown(
            id="market-selector",
            options=[{"label": k, "value": v} for k, v in API_ENDPOINTS.items()],
            value=API_ENDPOINTS["Premarket Movers"],
            clearable=False,
            style={"width": "300px", "marginBottom": "20px"},
        ),
        
        # Interval component set to fetch live data every 15 seconds (15,000 ms)
        dcc.Interval(
            id="interval-component",
            interval=15_000,
            n_intervals=0,
        ),
        
        # Target container refreshed dynamically
        html.Div(id="table-container"),
    ],
    style={"padding": "24px", "backgroundColor": "#0d1410", "minHeight": "100vh"},
)


@app.callback(
    Output("table-container", "children"),
    Input("interval-component", "n_intervals"),
    Input("market-selector", "value"),
)
def update_table_automatically(n_intervals: int, selected_api_url: str):
    df, error_msg = fetch_stock_top10(selected_api_url)

    if error_msg:
        return html.Div(
            f"Error updating stock data: {error_msg}",
            style={"color": "#ff6b6b", "fontFamily": "DM Sans, sans-serif"},
        )

    return build_table(
        frame=df,
        yellow_threshold=5.0,
        orange_threshold=10.0,
        red_threshold=20.0,
    )


if __name__ == "__main__":
    app.run_server(debug=True)
