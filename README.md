# Luma Market Tracker

A modular Plotly Dash market tracker. `main.py` owns the collapsible settings sidebar and app frame. The sub applications include separate Premarket and Open Market (Top Daily Gainers) trackers, a parabolic short inspector, an intraday tape, a daily stock analyzer with technical indicators and dividend history, and a normalized-price comparison app. The ticker-based sub-app selections use the shared sidebar ticker list.

## Run locally

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:8050.

The live source is fetched when the selected market app loads and every configured refresh interval. The initial app selection is recalculated on each page load using US Eastern time: Premarket from 4:00 a.m. until 9:30 a.m., and Open Market during open-market hours (9:30 a.m. to 8:00 p.m.). Open Market remains the default at other times.

## Deploy on Render

Create a new **Blueprint** in Render and select this repository. The included `render.yaml` configures the Python web service and its Gunicorn start command.

If you created the service manually, set the Start Command to `gunicorn main:server --bind 0.0.0.0:$PORT`.