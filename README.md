## Live App
https://uk-rates-fx-monitor-wmhywnxkwz2tjejddv3nx8.streamlit.app


# UK Rates & FX Market Monitor (BigQuery + Streamlit)

A small finance analytics portfolio project:
- **Warehouse:** Google BigQuery (SQL views for derived metrics)
- **Data sources:** Bank of England (Official Bank Rate, series IUDBEDR) + ECB Data Portal (GBP/EUR)
- **App:** Streamlit dashboard querying BigQuery

## Architecture: 
See ARCHITECTURE.md

## Local run

1) Create `.streamlit/secrets.toml` and paste your **service account JSON fields** under `[gcp_service_account]`.

2) Install:
```bash
pip install -r requirements.txt
```

3) Load data to BigQuery (first time):
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/service_account.json"
python scripts/load_boe_bank_rate.py --project YOUR_PROJECT --dataset market_data
python scripts/load_ecb_fx.py --project YOUR_PROJECT --dataset market_data
```

4) Create views:
- Open `sql/views.sql`, replace `YOUR_PROJECT`, run in BigQuery.

5) Run app:
```bash
streamlit run app.py
```

## Deployment (Streamlit Community Cloud)
Copy the contents of `.streamlit/secrets.toml` into your app's **Secrets** in Streamlit Cloud.
