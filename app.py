from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output, dcc, html


APP_COLORS = {
    "ink": "#17221b",
    "muted": "#718078",
    "mint": "#b9e8d2",
    "forest": "#23513e",
    "coral": "#f28f70",
    "cream": "#f7f6ef",
    "line": "#dfe7df",
}


def build_transactions() -> pd.DataFrame:
    rows = [
        ("2026-04-28", "Harbor Market", "Groceries", -84.20, "Everyday"),
        ("2026-04-27", "Acme Payroll", "Income", 4820.00, "Main account"),
        ("2026-04-25", "Metro Electric", "Home", -118.42, "Bills"),
        ("2026-04-22", "Kite & Co.", "Shopping", -72.90, "Everyday"),
        ("2026-04-20", "Brightline Internet", "Home", -65.00, "Bills"),
        ("2026-04-18", "Oak Cafe", "Dining", -24.80, "Everyday"),
        ("2026-04-16", "Acme Payroll", "Income", 4820.00, "Main account"),
        ("2026-04-13", "Northwind Pharmacy", "Health", -36.55, "Everyday"),
        ("2026-04-10", "Tidal Fitness", "Wellness", -49.00, "Everyday"),
        ("2026-04-08", "Lumen Mobile", "Home", -48.00, "Bills"),
        ("2026-04-05", "Acme Payroll", "Income", 4820.00, "Main account"),
        ("2026-04-02", "City Rail", "Transport", -41.25, "Everyday"),
    ]
    frame = pd.DataFrame(rows, columns=["date", "merchant", "category", "amount", "account"])
    frame["date"] = pd.to_datetime(frame["date"])
    return frame


TRANSACTIONS = build_transactions()


def money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def empty_figure(message: str) -> go.Figure:
    figure = go.Figure()
    figure.update_layout(
        annotations=[{"text": message, "showarrow": False, "font": {"color": APP_COLORS["muted"], "size": 15}}],
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis={"visible": False},
        yaxis={"visible": False},
        margin={"t": 10, "r": 10, "b": 10, "l": 10},
    )
    return figure


def metric_card(label: str, value: str, change: str, tone: str = "positive") -> html.Div:
    return html.Div(
        [html.P(label, className="metric-label"), html.H2(value), html.Span(change, className=f"metric-change {tone}")],
        className="metric-card",
    )


app = Dash(__name__, title="Luma Finance")
server = app.server

app.layout = html.Div(
    [
        html.Aside(
            [
                html.Div([html.Div("L", className="brand-mark"), html.Span("luma", className="brand-name")], className="brand"),
                html.Div("YOUR MONEY, IN FOCUS", className="eyebrow sidebar-eyebrow"),
                html.Nav(
                    [
                        html.Div([html.Span("⌂", className="nav-icon"), "Overview"], className="nav-item active"),
                        html.Div([html.Span("↗", className="nav-icon"), "Cash flow"], className="nav-item"),
                        html.Div([html.Span("◌", className="nav-icon"), "Budgets"], className="nav-item"),
                        html.Div([html.Span("⌁", className="nav-icon"), "Accounts"], className="nav-item"),
                    ],
                    className="nav-list",
                ),
                html.Div(
                    [
                        html.P("MONTHLY TARGET", className="eyebrow"),
                        html.Div([html.Strong("$1,280"), html.Span(" / $1,600")], className="target-value"),
                        html.Div(html.Div(className="target-progress"), className="target-track"),
                        html.P("$320 left in your flexible budget", className="target-note"),
                    ],
                    className="sidebar-target",
                ),
                html.Div([html.Div("JD", className="avatar"), html.Div([html.Strong("Jordan Davis"), html.Small("Personal plan")])], className="profile"),
            ],
            className="sidebar",
        ),
        html.Main(
            [
                html.Header(
                    [
                        html.Div([html.P("MONDAY, APRIL 28, 2026", className="eyebrow"), html.H1("Good morning, Jordan.")]),
                        html.Button("+ Add transaction", className="add-button"),
                    ],
                    className="topbar",
                ),
                html.Div(
                    [
                        html.Div([html.P("TOTAL BALANCE", className="eyebrow balance-label"), html.Div(id="balance-value", className="balance-value"), html.Div("Across 3 connected accounts", className="balance-note")], className="balance-panel"),
                        html.Div([html.P("THIS MONTH", className="eyebrow"), html.Div("$3,082", className="income-value"), html.Div([html.Span("↑ 8.4%", className="trend-up"), " vs. last month"], className="balance-note")], className="income-panel"),
                        html.Div([html.P("SAVINGS RATE", className="eyebrow"), html.Div("31.6%", className="income-value"), html.Div("You're ahead of your 25% target", className="balance-note")], className="income-panel"),
                    ],
                    className="hero-grid",
                ),
                html.Div([html.H2("Your financial rhythm"), html.Div([dcc.Dropdown(id="account-filter", options=[{"label": "All accounts", "value": "All"}, {"label": "Everyday", "value": "Everyday"}, {"label": "Bills", "value": "Bills"}, {"label": "Main account", "value": "Main account"}], value="All", clearable=False, className="filter"), dcc.Dropdown(id="period-filter", options=[{"label": "Last 30 days", "value": 30}, {"label": "Last 90 days", "value": 90}], value=30, clearable=False, className="filter period-filter")], className="section-heading")], className="section-header"),
                html.Div(id="metric-row", className="metric-grid"),
                html.Div(
                    [
                        html.Section([html.Div([html.H3("Cash flow"), html.Span("Income vs. spending", className="section-caption")], className="chart-heading"), dcc.Graph(id="cashflow-chart", config={"displayModeBar": False})], className="surface chart-surface wide"),
                        html.Section([html.Div([html.H3("Where it goes"), html.Span("This month", className="section-caption")], className="chart-heading"), dcc.Graph(id="spend-chart", config={"displayModeBar": False})], className="surface chart-surface"),
                    ],
                    className="charts-grid",
                ),
                html.Section([html.Div([html.Div([html.H3("Recent activity"), html.Span("Your latest transactions", className="section-caption")], className="chart-heading"), html.Button("View all", className="text-button")], className="table-heading"), html.Div(id="transaction-table")], className="surface activity-surface"),
                html.Footer("Luma is a private demo dashboard. No real financial data is connected.", className="footer"),
            ],
            className="main-content",
        ),
    ],
    className="app-shell",
)


@app.callback(
    Output("balance-value", "children"),
    Output("metric-row", "children"),
    Output("cashflow-chart", "figure"),
    Output("spend-chart", "figure"),
    Output("transaction-table", "children"),
    Input("account-filter", "value"),
    Input("period-filter", "value"),
)
def update_dashboard(account: str, period: int):
    filtered = TRANSACTIONS.copy()
    if account != "All":
        filtered = filtered[filtered["account"] == account]
    filtered = filtered[filtered["date"] >= filtered["date"].max() - timedelta(days=period)]

    balance = 28460.72 if account == "All" else {"Everyday": 4260.72, "Bills": 13800.00, "Main account": 10400.00}[account]
    expenses = abs(filtered.loc[filtered["amount"] < 0, "amount"].sum())
    income = filtered.loc[filtered["amount"] > 0, "amount"].sum()
    savings = max(income - expenses, 0)
    metrics = [metric_card("INCOME", money(income), "↑ 12.8% vs. last period"), metric_card("SPENDING", money(expenses), "↓ 4.2% vs. last period", "calm"), metric_card("LEFT TO SPEND", money(max(1600 - expenses, 0)), "On track this month", "calm")]

    cashflow = filtered.copy()
    cashflow["day"] = cashflow["date"].dt.strftime("%b %d")
    daily = cashflow.groupby(["date", "day"], as_index=False)["amount"].sum()
    daily["income"] = daily["amount"].where(daily["amount"] > 0, 0)
    daily["spending"] = daily["amount"].where(daily["amount"] < 0, 0).abs()
    cash_figure = go.Figure()
    cash_figure.add_trace(go.Bar(x=daily["day"], y=daily["income"], name="Income", marker_color=APP_COLORS["mint"], hovertemplate="$%{y:,.0f}<extra>Income</extra>"))
    cash_figure.add_trace(go.Bar(x=daily["day"], y=daily["spending"], name="Spending", marker_color=APP_COLORS["coral"], hovertemplate="$%{y:,.0f}<extra>Spending</extra>"))
    cash_figure.update_layout(barmode="group", showlegend=True, legend={"orientation": "h", "y": 1.12, "x": 0}, margin={"t": 20, "r": 10, "b": 5, "l": 0}, height=280, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font={"family": "DM Sans", "color": APP_COLORS["muted"]}, xaxis={"showgrid": False, "tickfont": {"size": 10}}, yaxis={"showgrid": True, "gridcolor": "#edf1ed", "tickprefix": "$", "tickfont": {"size": 10}})

    spend = filtered[filtered["amount"] < 0].groupby("category", as_index=False)["amount"].sum()
    spend["amount"] = spend["amount"].abs()
    spend_figure = px.pie(spend, values="amount", names="category", hole=0.7, color_discrete_sequence=[APP_COLORS["forest"], APP_COLORS["coral"], "#e5c878", "#90b9a5", "#b8c7bd"])
    spend_figure.update_traces(textinfo="none", hovertemplate="%{label}: $%{value:,.0f}<extra></extra>")
    spend_figure.update_layout(showlegend=True, legend={"font": {"size": 11}, "orientation": "v", "x": 0.98, "xanchor": "right"}, margin={"t": 0, "r": 0, "b": 0, "l": 0}, height=280, paper_bgcolor="rgba(0,0,0,0)", font={"family": "DM Sans", "color": APP_COLORS["muted"]}, annotations=[{"text": money(savings), "showarrow": False, "font": {"size": 22, "color": APP_COLORS["ink"]}}, {"text": "saved", "showarrow": False, "y": 0.39, "font": {"size": 11, "color": APP_COLORS["muted"]}}])

    table_rows = []
    for _, row in filtered.sort_values("date", ascending=False).head(6).iterrows():
        amount_class = "amount positive-amount" if row["amount"] > 0 else "amount"
        table_rows.append(html.Div([html.Div(row["merchant"], className="merchant"), html.Div(row["category"], className="category-pill"), html.Div(row["date"].strftime("%b %d, %Y"), className="transaction-date"), html.Div(("+" if row["amount"] > 0 else "") + money(row["amount"]), className=amount_class)], className="transaction-row"))
    return money(balance), metrics, cash_figure, spend_figure, table_rows


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)