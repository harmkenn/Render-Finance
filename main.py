import dash
from dash import Input, Output, dcc, html

# Ensure PAGES is imported here from fishing
from fishing import PAGES, build_table, fetch_stock_top10, scrape_stock_top10

app = dash.Dash(__name__)
server = app.server  # Required for Gunicorn on Render


def get_default_page():
    return list(PAGES.keys())[0] if PAGES else ""


def sidebar():
    return html.Div(
        [
            html.H2("Market Dash", className="sidebar-title"),
            dcc.Dropdown(
                id="page-select",
                options=[{"label": name, "value": name} for name in PAGES],
                value=get_default_page(),
                clearable=False,
                className="sidebar-control",
            ),
            dcc.Interval(
                id="interval-component",
                interval=15_000,  # Auto-refresh every 15 seconds
                n_intervals=0,
            ),
        ],
        className="sidebar",
    )


app.layout = html.Div(
    [
        sidebar(),
        html.Div(id="page-content", className="content"),
    ]
)


@app.callback(
    Output("page-content", "children"),
    Input("page-select", "value"),
    Input("interval-component", "n_intervals"),
)
def update_table(selected_page: str, n_intervals: int):
    # Lookup URL from PAGES dict using the dropdown selection
    target_url = PAGES.get(selected_page, get_default_page())
    df, error_msg = fetch_stock_top10(target_url)

    if error_msg:
        return html.Div(f"Error fetching data: {error_msg}", className="error-message")

    return build_table(
        frame=df,
        yellow_threshold=5.0,
        orange_threshold=10.0,
        red_threshold=20.0,
    )


if __name__ == "__main__":
    app.run_server(debug=True)
