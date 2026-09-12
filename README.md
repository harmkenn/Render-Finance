# Luma Market Tracker

A responsive Plotly Dash stock tracker matching the Streamlit workflow: it fetches Premarket Movers or Top Daily Gainers from StockAnalysis, filters out low-price and low-volume rows, highlights large gainers, and refreshes automatically.

## Run locally

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:8050.

The live source is fetched when the page loads and every configured refresh interval. The default market view follows US Eastern time: Top Daily Gainers during weekday market hours, otherwise Premarket Movers.

## Deploy on Render

Create a new **Blueprint** in Render and select this repository. The included `render.yaml` configures the Python web service and its Gunicorn start command.

If you created the service manually, set the Start Command to `gunicorn app:server --bind 0.0.0.0:$PORT`.