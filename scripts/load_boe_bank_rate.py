"""Load BoE Official Bank Rate (IUDBEDR) into BigQuery.

This uses the BoE Database download endpoint (NOT HTML scraping).
Endpoint + parameters are documented by the BoE Database help page.

Typical usage (macOS/Linux):
  export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service_account.json"
  python scripts/load_boe_bank_rate.py --project YOUR_PROJECT --dataset market_data

"""
import argparse
import io
from datetime import datetime, timezone

import pandas as pd
import requests
from google.cloud import bigquery

BOE_ENDPOINT = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes"

def fetch_boe_series(series_code: str, date_from: str = "01/Jan/2010", date_to: str = "now") -> pd.DataFrame:
    params = {
        "Datefrom": date_from,
        "Dateto": date_to,
        "SeriesCodes": series_code,
        "CSVF": "TN",        # Tabular, no titles
        "UsingCodes": "Y",
        "VPD": "Y",          # include provisional data if any
        "VFD": "N",
    }
    # Add a basic user-agent; occasionally helps with public endpoints.
    headers = {"User-Agent": "uk-rates-fx-monitor/0.1"}
    r = requests.get(BOE_ENDPOINT, params=params, headers=headers, timeout=30)
    r.raise_for_status()

    df = pd.read_csv(io.BytesIO(r.content))
    if "DATE" not in df.columns:
        raise ValueError(f"Unexpected BoE CSV format. Columns: {df.columns.tolist()}")

    # Wide -> long
    df_long = df.melt(id_vars=["DATE"], var_name="series_code", value_name="value")
    df_long["dt"] = pd.to_datetime(df_long["DATE"], format="%d %b %Y", errors="coerce").dt.date
    df_long["value"] = pd.to_numeric(df_long["value"], errors="coerce")
    df_long = df_long.dropna(subset=["dt", "value"])
    df_long = df_long[["dt", "series_code", "value"]]
    df_long["load_ts"] = datetime.now(timezone.utc)
    return df_long

def load_to_bq(df: pd.DataFrame, project: str, dataset: str, table: str) -> None:
    client = bigquery.Client(project=project)
    table_id = f"{project}.{dataset}.{table}"
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        schema=[
            bigquery.SchemaField("dt", "DATE"),
            bigquery.SchemaField("series_code", "STRING"),
            bigquery.SchemaField("value", "FLOAT"),
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
    ap.add_argument("--series", default="IUDBEDR")
    args = ap.parse_args()

    df = fetch_boe_series(args.series)
    load_to_bq(df, args.project, args.dataset, "raw_boe_series")

if __name__ == "__main__":
    main()
