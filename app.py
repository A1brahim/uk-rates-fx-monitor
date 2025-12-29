import streamlit as st
import pandas as pd
from google.oauth2 import service_account
from google.cloud import bigquery
import os
import sys
import pickle
from typing import Optional
import hashlib
from datetime import date as dt_date
import subprocess
import shutil
import json
import tempfile



st.set_page_config(page_title="UK Rates & FX Market Monitor", layout="wide")

# --- Credentials (Service Account JSON stored in Streamlit secrets) ---
# Streamlit docs show storing the key fields under [gcp_service_account] in .streamlit/secrets.toml
# and building credentials from st.secrets["gcp_service_account"].
credentials = service_account.Credentials.from_service_account_info(
    st.secrets["gcp_service_account"]
)

project_id = st.secrets["gcp_service_account"]["project_id"]
dataset = st.secrets.get("bq_dataset", "market_data")

client = bigquery.Client(credentials=credentials, project=project_id)

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))



ADC_KEYFILE = os.path.join(REPO_ROOT, ".cache", "gcp_service_account.json")


# Helper to convert Streamlit secrets (AttrDict) to plain JSON-serializable types
def _to_plain(obj):
    """Convert Streamlit AttrDict / nested structures to plain JSON-serializable types."""
    # Streamlit secrets sections are often `AttrDict` (dict-like but not JSON-serializable)
    if hasattr(obj, "items"):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(x) for x in obj]
    return obj


def ensure_adc_keyfile() -> str:
    """Write st.secrets['gcp_service_account'] to a local JSON file for ADC.

    Loader scripts run in a subprocess (outside Streamlit), so they can't read Streamlit
    secrets directly. By writing the same service account to a JSON file and exporting
    GOOGLE_APPLICATION_CREDENTIALS for the subprocess, the scripts can authenticate.
    """
    os.makedirs(os.path.dirname(ADC_KEYFILE), exist_ok=True)

    acct = None
    try:
        acct = st.secrets.get("gcp_service_account")
    except Exception:
        acct = None

    # If secrets aren't available for some reason, fall back to whatever the environment provides.
    if not acct:
        return ADC_KEYFILE

    plain_acct = _to_plain(acct)
    payload = json.dumps(plain_acct, sort_keys=True)

    needs_write = True
    if os.path.exists(ADC_KEYFILE):
        try:
            with open(ADC_KEYFILE, "r", encoding="utf-8") as f:
                needs_write = (f.read() != payload)
        except Exception:
            needs_write = True

    if needs_write:
        with open(ADC_KEYFILE, "w", encoding="utf-8") as f:
            # Write valid service-account JSON for ADC
            f.write(payload)

    return ADC_KEYFILE


def run_loader(script_rel_path: str, args: list[str]) -> None:
    """Run a loader script in a subprocess and surface stdout/stderr in Streamlit."""
    python_exe = sys.executable or shutil.which("python3") or shutil.which("python")
    if not python_exe:
        st.error("Could not find a Python executable to run loader scripts.")
        st.stop()

    script_abs_path = os.path.abspath(os.path.join(REPO_ROOT, script_rel_path))
    if not os.path.exists(script_abs_path):
        st.error(f"Loader script not found: {script_abs_path}")
        st.stop()

    env = os.environ.copy()
    keyfile = ensure_adc_keyfile()
    if os.path.exists(keyfile):
        env["GOOGLE_APPLICATION_CREDENTIALS"] = keyfile
    # Helpful default for some client libs (scripts still receive --project)
    env.setdefault("GOOGLE_CLOUD_PROJECT", project_id)

    cmd = [python_exe, script_abs_path] + args

    res = subprocess.run(
        cmd,
        cwd=REPO_ROOT,  # run from repo root so relative paths inside scripts work
        env=env,
        capture_output=True,
        text=True,
    )

    if res.returncode != 0:
        st.error(f"Loader failed: {script_rel_path} (exit {res.returncode})")
        if res.stdout.strip():
            st.code(res.stdout, language="text")
        if res.stderr.strip():
            st.code(res.stderr, language="text")
        st.stop()

CACHE_DIR = ".cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def _cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.pkl")

def _save_df(df: pd.DataFrame, key: str) -> None:
    with open(_cache_path(key), "wb") as f:
        pickle.dump(df, f)

def _load_df(key: str) -> Optional[pd.DataFrame]:
    path = _cache_path(key)
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    return None

@st.cache_data(ttl=600)
def query_df(sql: str, cache_key: Optional[str] = None) -> pd.DataFrame:
    # Ensure different SQL (e.g., different date ranges) gets different cache files
    if cache_key is None:
        cache_key = hashlib.md5(sql.encode("utf-8")).hexdigest()

    try:
        df = client.query(sql).to_dataframe(create_bqstorage_client=False)
        _save_df(df, cache_key)
        return df
    except Exception as e:
        cached = _load_df(cache_key)
        if cached is not None:
            st.warning(f"BigQuery failed ({type(e).__name__}: {e}) — showing last cached data.")
            return cached
        raise e

st.title("UK Rates & FX Market Monitor (BigQuery + Streamlit)")

# -------- Date filter (sidebar) --------
bounds_sql = f"""
SELECT
  (SELECT MIN(dt) FROM `{project_id}.{dataset}.v_boe_bank_rate`) AS min_rate_dt,
  (SELECT MAX(dt) FROM `{project_id}.{dataset}.v_boe_bank_rate`) AS max_rate_dt,
  (SELECT MIN(dt) FROM `{project_id}.{dataset}.v_fx_gbpeur`) AS min_fx_dt,
  (SELECT MAX(dt) FROM `{project_id}.{dataset}.v_fx_gbpeur`) AS max_fx_dt
"""
bounds = query_df(bounds_sql).iloc[0]
min_date = min(bounds["min_rate_dt"], bounds["min_fx_dt"])
max_date = max(bounds["max_rate_dt"], bounds["max_fx_dt"])


st.sidebar.header("Filters")

min_d = pd.to_datetime(min_date).date()
max_d = pd.to_datetime(max_date).date()

default_start = (pd.to_datetime(max_date) - pd.Timedelta(days=365)).date()
default_end = max_d

# Let Streamlit presets work (they use today's date)
ui_max = max(max_d, dt_date.today())

date_sel = st.sidebar.date_input(
    "Date range",
    value=(default_start, default_end),
    min_value=min_d,
    max_value=ui_max,
)

# Streamlit can temporarily return a single date while selecting
if isinstance(date_sel, (tuple, list)) and len(date_sel) == 2:
    start_date, end_date = date_sel
else:
    start_date = end_date = date_sel

# Clamp to available data dates for querying
data_start, data_end = min_d, max_d
if end_date > data_end:
    st.sidebar.caption(f"Data available up to {data_end} — using that as end date.")
end_date = min(end_date, data_end)
start_date = max(start_date, data_start)

# Safety: if somehow reversed
if start_date > end_date:
    start_date, end_date = end_date, start_date


st.sidebar.divider()
st.sidebar.subheader("Data refresh")

if st.sidebar.button("Refresh BoE + ECB data"):
    st.sidebar.info("Running loaders...")

    run_loader(
        "scripts/load_boe_bank_rate.py",
        ["--project", project_id, "--dataset", dataset, "--series", "IUDBEDR"],
    )

    run_loader(
        "scripts/load_ecb_fx.py",
        ["--project", project_id, "--dataset", dataset],
    )

    st.cache_data.clear()

    st.sidebar.success("Refresh complete. Reloading…")
    st.rerun()
    

# -------- Queries (filtered) --------
bank_rate_sql = f"""
SELECT dt, bank_rate, regime
FROM `{project_id}.{dataset}.v_boe_bank_rate`
WHERE dt BETWEEN DATE('{start_date}') AND DATE('{end_date}')
ORDER BY dt
"""

fx_sql = f"""
SELECT dt, gbp_eur, log_return, vol_20d
FROM `{project_id}.{dataset}.v_fx_gbpeur`
WHERE dt BETWEEN DATE('{start_date}') AND DATE('{end_date}')
ORDER BY dt
"""

df_rate = query_df(bank_rate_sql)
df_fx = query_df(fx_sql)

if df_rate.empty or df_fx.empty:
    st.error("No data returned for this date range.")
    st.stop()

# -------- Freshness (for KPI + table) --------
fresh_sql = f"""
SELECT 'raw_boe_series' AS table_name, MAX(load_ts) AS latest_load_ts
FROM `{project_id}.{dataset}.raw_boe_series`
UNION ALL
SELECT 'raw_ecb_fx' AS table_name, MAX(load_ts) AS latest_load_ts
FROM `{project_id}.{dataset}.raw_ecb_fx`
"""
fresh = query_df(fresh_sql)

# -------- ROI #1: KPI row --------
k1, k2, k3, k4 = st.columns(4)

latest_rate = df_rate.iloc[-1]["bank_rate"]
latest_regime = df_rate.iloc[-1]["regime"]
latest_fx = df_fx.iloc[-1]["gbp_eur"]
latest_vol = df_fx.iloc[-1]["vol_20d"]

k1.metric("Bank Rate", f"{latest_rate:.2f}%", latest_regime)
k2.metric("GBP/EUR", f"{latest_fx:.4f}")
k3.metric("20D Vol", f"{latest_vol:.4f}")
k4.metric("Latest load", str(fresh["latest_load_ts"].max()))

# -------- Charts + tables --------
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Official Bank Rate (BoE)")
    st.line_chart(df_rate.set_index("dt")[["bank_rate"]])
    st.dataframe(df_rate.tail(12), width="stretch")

with col2:
    st.subheader("GBP/EUR (ECB) + returns")
    st.line_chart(df_fx.set_index("dt")[["gbp_eur"]])
    st.caption("Log return & 20-day rolling vol (computed in SQL)")
    st.dataframe(df_fx.tail(12), width="stretch")

st.divider()
st.subheader("Freshness checks")
st.dataframe(fresh, width="stretch")
