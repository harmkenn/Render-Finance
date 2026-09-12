from __future__ import annotations

from datetime import datetime
from functools import lru_cache

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytz
import yfinance as yf
from dash import dcc, html

def _number(value: object, default: float = 0.0) -> float:
    number = pd.to_numeric(value, errors="coerce")
    return default if pd.isna(number) else float(number)


def compute_short_metrics(ticker_obj: yf.Ticker, info: dict) -> dict:
    metrics = {"z_score": None, "f_score": None, "cash_runway_months": None, "cash_burn_monthly": None, "ctb_estimated": None, "share_growth_yoy": None}
    try:
        balance = ticker_obj.quarterly_balance_sheet
        income = ticker_obj.quarterly_financials
        cash_flow = ticker_obj.quarterly_cashflow
        if balance is None or balance.empty or income is None or income.empty:
            balance, income, cash_flow = ticker_obj.balance_sheet, ticker_obj.financials, ticker_obj.cashflow
        if balance is not None and not balance.empty and income is not None and not income.empty:
            assets = _number(balance.iloc[:, 0].get("Total Assets"), np.nan)
            liabilities = _number(balance.iloc[:, 0].get("Total Liabilities Net Minority Interest"), np.nan)
            current_assets = _number(balance.iloc[:, 0].get("Current Assets"), np.nan)
            current_liabilities = _number(balance.iloc[:, 0].get("Current Liabilities"), np.nan)
            cash = _number(balance.iloc[:, 0].get("Cash And Cash Equivalents"), np.nan)
            retained_earnings = _number(balance.iloc[:, 0].get("Retained Earnings"), 0)
            ebit = _number(income.iloc[:, 0].get("EBIT"), 0)
            revenue = _number(income.iloc[:, 0].get("Total Revenue"), np.nan)
            net_income = _number(income.iloc[:, 0].get("Net Income"), 0)
            market_cap = _number(info.get("marketCap"), 0)
            if all(pd.notna(value) and value > 0 for value in [assets, liabilities, current_assets, current_liabilities, revenue]):
                metrics["z_score"] = (1.2 * ((current_assets - current_liabilities) / assets) + 1.4 * (retained_earnings / assets) + 3.3 * (ebit / assets) + 0.6 * (market_cap / liabilities) + 0.999 * (revenue / assets))
            if cash_flow is not None and not cash_flow.empty and pd.notna(cash):
                free_cash_flow = cash_flow.iloc[:, 0].get("Free Cash Flow", np.nan)
                if pd.isna(free_cash_flow):
                    operating_cash_flow = cash_flow.iloc[:, 0].get("Operating Cash Flow", np.nan)
                    capital_expenditure = cash_flow.iloc[:, 0].get("Capital Expenditure", np.nan)
                    free_cash_flow = operating_cash_flow + (capital_expenditure if pd.notna(capital_expenditure) else 0) if pd.notna(operating_cash_flow) else np.nan
                if pd.notna(free_cash_flow):
                    monthly_burn = abs(free_cash_flow) / 3 if free_cash_flow < 0 else 0.0
                    metrics["cash_burn_monthly"] = monthly_burn
                    metrics["cash_runway_months"] = cash / monthly_burn if monthly_burn else 999.0
            if len(balance.columns) >= 2 and len(income.columns) >= 2:
                score = 0
                current_roa = net_income / assets if assets else 0
                if current_roa > 0: score += 1
                if cash_flow is not None and not cash_flow.empty:
                    operating_cash_flow = _number(cash_flow.iloc[:, 0].get("Operating Cash Flow"), np.nan)
                    if operating_cash_flow > 0: score += 1
                    if operating_cash_flow > net_income: score += 1
                previous_assets = _number(balance.iloc[:, 1].get("Total Assets"), np.nan)
                previous_income = _number(income.iloc[:, 1].get("Net Income"), np.nan)
                if pd.notna(previous_assets) and previous_assets and pd.notna(previous_income) and current_roa > previous_income / previous_assets: score += 1
                current_debt = _number(balance.iloc[:, 0].get("Long Term Debt"), 0)
                previous_debt = _number(balance.iloc[:, 1].get("Long Term Debt"), 0)
                if pd.notna(previous_assets) and previous_assets and current_debt / assets < previous_debt / previous_assets: score += 1
                previous_current_assets = _number(balance.iloc[:, 1].get("Current Assets"), np.nan)
                previous_current_liabilities = _number(balance.iloc[:, 1].get("Current Liabilities"), np.nan)
                if current_liabilities and pd.notna(previous_current_assets) and pd.notna(previous_current_liabilities) and current_assets / current_liabilities > previous_current_assets / previous_current_liabilities: score += 1
                metrics["f_score"] = score
            shares = _number(info.get("sharesOutstanding"), 0)
            previous_shares = _number(balance.iloc[:, -1].get("Share Issued"), 0)
            if shares and previous_shares: metrics["share_growth_yoy"] = (shares - previous_shares) / previous_shares * 100
        float_shares = _number(info.get("floatShares"), 0)
        short_ratio = _number(info.get("shortPercentOfFloat"), 0)
        metrics["ctb_estimated"] = 85.0 if 0 < float_shares < 5_000_000 else 45.0 if float_shares < 15_000_000 and short_ratio > 0.15 else 1.5 if float_shares > 50_000_000 else 12.0
    except Exception:
        pass
    return metrics


@lru_cache(maxsize=64)
def fetch_stock_data(symbol: str) -> dict | None:
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="5d", interval="1m", prepost=True)
        if history.empty:
            history = ticker.history(period="1mo", interval="1d", prepost=False)
        if history.empty:
            return None
        try: info = ticker.info or {}
        except Exception: info = {}
        latest_date = history.index.max().date()
        session = history[history.index.date == latest_date]
        if session.empty: session = history
        price = _number(session["Close"].iloc[-1])
        day_high, day_low = _number(session["High"].max()), _number(session["Low"].min())
        previous_close = _number(info.get("previousClose"), _number(session["Open"].iloc[0]))
        typical_price = (session["High"] + session["Low"] + session["Close"]) / 3
        volume_total = _number(session["Volume"].sum())
        vwap = _number((typical_price * session["Volume"]).sum() / volume_total if volume_total else price)
        average_volume = _number(info.get("averageVolume10days"), volume_total)
        rvol = volume_total / (average_volume / 6.5) if average_volume else 1.0
        gain = (price - previous_close) / previous_close if previous_close else 0
        drop = (day_high - price) / day_high if day_high else 0
        rejection = (day_high - price) / (day_high - previous_close) if day_high > previous_close else 0
        return {"symbol": symbol, "price": price, "day_high": day_high, "day_low": day_low, "prev_close": previous_close, "gain_24h": gain, "drop_from_high": drop, "rejection_pct": rejection, "vwap": vwap, "rvol": rvol, "float_shares": _number(info.get("floatShares")), "short_pct_float": _number(info.get("shortPercentOfFloat")), "hist": history, "trade_date": latest_date, **compute_short_metrics(ticker, info)}
    except Exception:
        return None


def estimate_borrow_status(data: dict) -> tuple[str, str]:
    ctb, float_shares, short_interest, gain = data["ctb_estimated"], data["float_shares"], data["short_pct_float"], data["gain_24h"]
    if ctb and ctb > 50: return "Extremely Hard to Borrow", f"Estimated CTB is high ({ctb:.1f}% APY)."
    if 0 < float_shares < 10_000_000 and gain > 0.40: return "Hard to Borrow Likely", "Micro-cap float with a large intraday spike."
    if short_interest > 0.20: return "Hard to Borrow Likely", "High short interest relative to float."
    if float_shares >= 50_000_000: return "Easy to Borrow Likely", "Large float and lower borrow pressure."
    return "Check Broker Inventory", "Verify current inventory with your broker."


def calculate_short_score(data: dict) -> dict:
    score = 0
    boosters = []
    penalties = []
    if data["gain_24h"] >= 1.5:
        score += 35
        boosters.append((35, "Price gain is at least 150%."))
    elif data["gain_24h"] >= 1:
        score += 25
        boosters.append((25, "Price gain is at least 100%."))
    elif data["gain_24h"] >= .5:
        score += 10
        boosters.append((10, "Price gain is at least 50%."))
    else:
        score -= 20
        penalties.append((-20, "Price gain is below 50%."))
    if data["rvol"] >= 15:
        score += 20
        boosters.append((20, "Relative volume is at least 15x."))
    elif data["rvol"] >= 5:
        score += 10
        boosters.append((10, "Relative volume is at least 5x."))
    vwap_diff = (data["price"] - data["vwap"]) / data["vwap"] * 100 if data["vwap"] else 0
    if vwap_diff >= 15:
        score += 25
        boosters.append((25, "Price is at least 15% above VWAP."))
    elif data["price"] > data["vwap"]:
        score += 15
        boosters.append((15, "Price is above VWAP."))
    else:
        score -= 15
        penalties.append((-15, "Price is at or below VWAP."))
    if 0 < data["float_shares"] <= 10_000_000:
        score += 10
        boosters.append((10, "Float is 10 million shares or less."))
    if data["z_score"] is not None and data["z_score"] < 1.8:
        score += 10
        boosters.append((10, "Altman Z-Score is below 1.8."))
    if data["cash_runway_months"] is not None and data["cash_runway_months"] < 6:
        score += 10
        boosters.append((10, "Cash runway is below six months."))
    if data["f_score"] is not None and data["f_score"] <= 2:
        score += 10
        boosters.append((10, "Piotroski F-Score is 2 or lower."))
    if data["drop_from_high"] <= .05:
        score -= 30
        penalties.append((-30, "Price is still within 5% of the day high."))
    if data["ctb_estimated"] and data["ctb_estimated"] > 50:
        score -= 15
        penalties.append((-15, "Estimated borrow cost is above 50% APY."))
    final_score = max(0, min(100, score))
    status = "TRIGGER" if final_score >= 75 and data["price"] > data["vwap"] else "ARMED" if final_score >= 55 else "CANDIDATE"
    return {"score": final_score, "status": status, "vwap_diff": vwap_diff, "boosters": boosters, "penalties": penalties, "message": "Extended above VWAP. Review the fade location and borrow risk." if status == "TRIGGER" else "Monitor price action and confirmation above VWAP." if status == "ARMED" else "Lacks a strong extension or has already broken down."}


def _value(label: str, value: str) -> html.Div:
    return html.Div([html.Div(label, className="inspector-label"), html.Div(value, className="inspector-value")], className="inspector-metric")


def _score_points(title: str, points: list[tuple[int, str]], empty_message: str, class_name: str) -> html.Div:
    items = [html.Li([html.Strong(f"{points_value:+d}"), f": {description}"]) for points_value, description in points]
    return html.Div([html.H3(title), html.Ul(items or [html.Li(empty_message)])], className=f"score-breakdown-column {class_name}")


def score_breakdown(score: dict) -> html.Div:
    return html.Div([
        _score_points("Positive Exhaustion Points", score["boosters"], "No positive setup points triggered.", "score-boosters"),
        _score_points("Warning Penalties", score["penalties"], "No active warning penalties.", "score-penalties"),
    ], className="score-breakdown")


def inspector_layout(tickers: list[str]) -> html.Div:
    return html.Div([
        html.Div([html.H2("Single-Ticker Parabolic Short Inspector"), html.P("Evaluate parabolic single-day spikes, VWAP extension, borrow risk, and fundamental stress.", className="intro-copy")], className="section-header"),
        html.Div([dcc.Dropdown(id="inspector-ticker", options=[{"label": ticker, "value": ticker} for ticker in tickers], value=tickers[0], clearable=False, className="inspector-ticker"), html.Button("Analyze stock", id="inspector-analyze", className="add-button")], className="inspector-controls"),
        html.Div(id="inspector-status", className="status-message"),
        html.Div(id="inspector-metrics", className="inspector-grid"),
        html.Div(id="inspector-summary", className="inspector-summary"),
        html.Section([html.H3("10-Day Intraday Baseline Chart"), dcc.Graph(id="inspector-chart", config={"displayModeBar": False})], className="surface inspector-section"),
        html.Section([html.H3("Technical Breakdown"), html.Div(id="inspector-technical", className="inspector-detail-grid")], className="surface inspector-section"),
        html.Section([html.H3("Micro-Cap Short Fundamentals & Criteria"), html.Div(id="inspector-fundamentals", className="inspector-detail-grid")], className="surface inspector-section"),
    ], id="inspector-content", style={"display": "none"})


def render_inspector(symbol: str):
    data = fetch_stock_data((symbol or "TQQQ").strip().upper())
    if not data: return "Could not retrieve data for this ticker.", [], {}, [], [], html.Div()
    score = calculate_short_score(data)
    borrow, borrow_reason = estimate_borrow_status(data)
    metrics = [_value("Short score", f"{score['score']}/100"), _value("Signal state", score["status"]), _value("Current price", f"${data['price']:.2f} ({data['gain_24h'] * 100:+.1f}%)"), _value("Borrow outlook", borrow)]
    hist = data["hist"].copy()
    eastern = pytz.timezone("US/Eastern")
    hist.index = hist.index.tz_localize("UTC").tz_convert(eastern) if hist.index.tz is None else hist.index.tz_convert(eastern)
    figure = go.Figure(go.Scatter(x=hist.index, y=hist["Close"], mode="lines", name="Price", line={"color": "#00B4D8", "width": 1.5}))
    figure.add_hline(y=data["prev_close"], line_dash="dash", line_color="gray", annotation_text=f"Prev Close (${data['prev_close']:.2f})")
    figure.add_hline(y=data["vwap"], line_dash="dot", line_color="orange", annotation_text=f"VWAP (${data['vwap']:.2f})")
    for trade_date in sorted(set(hist.index.date)):
        day_start = datetime.combine(trade_date, datetime.min.time())
        premarket_start = eastern.localize(day_start.replace(hour=4))
        market_open = eastern.localize(day_start.replace(hour=9, minute=30))
        market_close = eastern.localize(day_start.replace(hour=16))
        aftermarket_end = eastern.localize(day_start.replace(hour=20))
        figure.add_vrect(x0=premarket_start, x1=market_open, fillcolor="rgba(255, 215, 0, 0.10)", layer="below", line_width=0)
        figure.add_vrect(x0=market_close, x1=aftermarket_end, fillcolor="rgba(0, 180, 216, 0.10)", layer="below", line_width=0)
    figure.update_layout(template="plotly_dark", height=450, margin={"l": 20, "r": 20, "t": 30, "b": 20}, hovermode="x unified", xaxis_title="Date/Time (US/Eastern)", yaxis_title="Stock Price ($)")
    technical = [_value("Day high", f"${data['day_high']:.2f}"), _value("Previous close", f"${data['prev_close']:.2f}"), _value("Drop from high", f"{data['drop_from_high'] * 100:.1f}%"), _value("Today VWAP", f"${data['vwap']:.2f} ({score['vwap_diff']:+.1f}%)"), _value("RVOL proxy", f"{data['rvol']:.1f}x"), _value("Float size", f"{data['float_shares'] / 1e6:.1f}M" if data['float_shares'] else "N/A"), _value("Borrow note", borrow_reason)]
    fundamentals = [_value("Altman Z-Score", f"{data['z_score']:.2f}" if data['z_score'] is not None else "N/A"), _value("Piotroski F-Score", f"{data['f_score']}/9" if data['f_score'] is not None else "N/A"), _value("Cash runway", f"{data['cash_runway_months']:.1f} months" if data['cash_runway_months'] is not None else "N/A"), _value("Monthly cash burn", f"${data['cash_burn_monthly'] / 1e6:.2f}M" if data['cash_burn_monthly'] else "N/A"), _value("Estimated CTB", f"{data['ctb_estimated']:.1f}% APY" if data['ctb_estimated'] is not None else "N/A"), _value("Share dilution", f"{data['share_growth_yoy']:+.1f}% YoY" if data['share_growth_yoy'] is not None else "N/A")]
    return f"{symbol.upper()} · {score['message']}", metrics, figure, score_breakdown(score), technical, fundamentals
