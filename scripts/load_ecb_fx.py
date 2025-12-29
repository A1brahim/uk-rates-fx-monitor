"""Load ECB FX series (GBP/EUR) into BigQuery using the ECB Data Portal API (SDMX).

Typical usage:
  export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service_account.json"
  python scripts/load_ecb_fx.py --project YOUR_PROJECT --dataset market_data

"""
import argparse
import io
from datetime import datetime, timezone

import pandas as pd
import requests
from google.cloud import bigquery

# ECB Data Portal API (SDMX)
# Series key is documented by ECB: EXR.D.GBP.EUR.SP00.A (daily GBP vs EUR spot, average)
ECB_CSV_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.GBP.EUR.SP00.A"
DEFAULT_START = "2010-01-01"

def fetch_ecb_gbpeur(start_period: str = DEFAULT_START) -> pd.DataFrame:
    params = {
        "format": "csvdata",
        "startPeriod": start_period,
    }
    headers = {"User-Agent": "uk-rates-fx-monitor/0.1"}
    r = requests.get(ECB_CSV_URL, params=params, headers=headers, timeout=30)
    r.raise_for_status()

    df = pd.read_csv(io.BytesIO(r.content))
    # ECB CSV typically contains TIME_PERIOD and OBS_VALUE.
    if "TIME_PERIOD" not in df.columns or "OBS_VALUE" not in df.columns:
        raise ValueError(f"Unexpected ECB CSV format. Columns: {df.columns.tolist()}")

    out = pd.DataFrame({
        "dt": pd.to_datetime(df["TIME_PERIOD"], errors="coerce").dt.date,
        "ccy": "GBP",
        "per_eur": pd.to_numeric(df["OBS_VALUE"], errors="coerce"),
    }).dropna(subset=["dt", "per_eur"])

    out["load_ts"] = datetime.now(timezone.utc)
    return out

def load_to_bq(df: pd.DataFrame, project: str, dataset: str, table: str) -> None:
    client = bigquery.Client(project=project)
    table_id = f"{project}.{dataset}.{table}"
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        schema=[
            bigquery.SchemaField("dt", "DATE"),
            bigquery.SchemaField("ccy", "STRING"),
            bigquery.SchemaField("per_eur", "FLOAT"),
            bigquery.SchemaField("load_ts", "TIMESTAMP"),
        ],
    )
    job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()
    print(f"Loaded {len(df):,} rows into {table_id}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--dataset", default="market_data")
    ap.add_argument("--start", default=DEFAULT_START)
    args = ap.parse_args()

    df = fetch_ecb_gbpeur(args.start)
    load_to_bq(df, args.project, args.dataset, "raw_ecb_fx")

if __name__ == "__main__":
    main()
