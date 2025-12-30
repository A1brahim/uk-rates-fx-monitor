# Architecture
BoE/ECB public data → Python loaders → BigQuery (raw tables + SQL views) → Streamlit UI

1. Sources
   - Bank of England (Official Bank Rate, series `IUDBEDR`)
   - ECB Data Portal (GBP/EUR)

2. Ingestion (Python)
   - `scripts/load_boe_bank_rate.py`
   - `scripts/load_ecb_fx.py`

3. Storage & transforms (BigQuery)
   - Raw tables: `raw_boe_series`, `raw_ecb_fx`
   - Derived views (metrics): `sql/views.sql` (e.g., returns, rolling vol)

4. App (Streamlit)
   - `app.py` queries BigQuery views, renders KPIs/charts/tables
   - “Refresh BoE + ECB data” triggers the loader scripts from the UI
