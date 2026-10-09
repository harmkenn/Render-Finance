import datetime
import zoneinfo
import pandas as pd
import requests
from bs4 import BeautifulSoup

def get_active_market_window() -> str:
    """Determine active market session based on US Eastern Time."""
    now = datetime.datetime.now(zoneinfo.ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return "Overnight"
    
    current_time = now.time()
    if datetime.time(4, 0) <= current_time < datetime.time(9, 30):
        return "Pre Market"
    elif datetime.time(9, 30) <= current_time < datetime.time(16, 0):
        return "Open Market"
    elif datetime.time(16, 0) <= current_time < datetime.time(20, 0):
        return "After Hours"
    else:
        return "Overnight"


def fetch_yahoo_prices(tickers: list[str]) -> tuple[dict[str, dict[str, str]], str]:
    """
    Query Yahoo Finance API directly to fetch both:
    1. Primary Price (Previous Close / Regular Price)
    2. Secondary Price (Premarket / After Hours / Overnight)
    """
    window = get_active_market_window()
    results = {}
    
    if not tickers:
        return results, window

    symbols = ",".join(tickers)
    # Direct Yahoo quote API query for fast response
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbols}"
    headers = {"User-Agent": USER_AGENT}

    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json().get("quoteResponse", {}).get("result", [])
            for item in data:
                symbol = item.get("symbol")
                
                # Primary price (regular close)
                prev_close = item.get("regularMarketPreviousClose") or item.get("regularMarketPrice")
                
                # Secondary extended hours prices
                pre_market = item.get("preMarketPrice")
                post_market = item.get("postMarketPrice")
                
                # Active price resolution
                if window == "Pre Market":
                    secondary = pre_market or item.get("regularMarketPrice")
                elif window == "After Hours":
                    secondary = post_market or item.get("regularMarketPrice")
                elif window == "Overnight":
                    # Overnight resolves to post-market/pre-market or the latest streaming quote
                    secondary = item.get("bid") or post_market or pre_market or prev_close
                else: # Regular Open Market
                    secondary = item.get("regularMarketPrice")

                results[symbol] = {
                    "Prev Close": f"${prev_close:.2f}" if prev_close else "N/A",
                    "Extended Price": f"${secondary:.2f}" if secondary else "N/A",
                }
    except Exception:
        pass

    return results, window


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
        
        symbol_column = next((col for col in frame.columns if "symbol" in str(col).lower() or "ticker" in str(col).lower()), frame.columns[0])
        price_column = next((col for col in frame.columns if "price" in str(col).lower()), None)
        volume_column = next((col for col in frame.columns if "volume" in str(col).lower()), None)
        
        if price_column:
            frame = frame[frame[price_column].map(parse_price) >= 0.80]
        if volume_column:
            frame = frame[frame[volume_column].map(parse_volume) >= 1_000]
        
        top_frame = frame.head(10).copy()
        
        # Retrieve primary and secondary prices from Yahoo
        tickers = top_frame[symbol_column].astype(str).tolist()
        yahoo_data, active_window = fetch_yahoo_prices(tickers)
        
        secondary_col_label = f"Yahoo {active_window}"
        
        top_frame["Yahoo Prev Close"] = top_frame[symbol_column].map(lambda t: yahoo_data.get(t, {}).get("Prev Close", "N/A"))
        top_frame[secondary_col_label] = top_frame[symbol_column].map(lambda t: yahoo_data.get(t, {}).get("Extended Price", "N/A"))

        # Reorder columns to place Yahoo prices side-by-side after the source price column
        cols = list(top_frame.columns)
        if price_column and price_column in cols:
            price_idx = cols.index(price_column)
            cols.remove("Yahoo Prev Close")
            cols.remove(secondary_col_label)
            cols.insert(price_idx + 1, "Yahoo Prev Close")
            cols.insert(price_idx + 2, secondary_col_label)
            top_frame = top_frame[cols]

        return top_frame, None
    except requests.RequestException as error:
        return None, f"Could not reach StockAnalysis: {error}"
    except (ValueError, IndexError) as error:
        return None, f"Could not read the market table: {error}"
