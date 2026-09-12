# Luma Finance

A responsive Plotly Dash finance dashboard with interactive account and time-period filters.

## Run locally

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:8050.

## Deploy on Render

Create a new **Blueprint** in Render and select this repository. The included `render.yaml` configures the Python web service and its Gunicorn start command.