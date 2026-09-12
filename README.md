# Luma Market Tracker

A modular Plotly Dash market tracker. `main.py` owns the collapsible settings sidebar and app frame; `fishing.py` is the first sub application and fetches Premarket Movers or Top Daily Gainers from StockAnalysis.

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

If you created the service manually, set the Start Command to `gunicorn main:server --bind 0.0.0.0:$PORT`.