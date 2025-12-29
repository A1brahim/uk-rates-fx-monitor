-- Replace YOUR_PROJECT below (or run these from the BigQuery UI after setting the project).
-- Dataset expected: market_data (or whatever you set as bq_dataset).

CREATE OR REPLACE VIEW `YOUR_PROJECT.market_data.v_boe_bank_rate` AS
WITH latest AS (
  SELECT *
  FROM `YOUR_PROJECT.market_data.raw_boe_series`
  QUALIFY load_ts = MAX(load_ts) OVER ()
),
daily AS (
  SELECT dt, value AS bank_rate
  FROM latest
  WHERE series_code = 'IUDBEDR'
)
SELECT
  dt,
  bank_rate,
  bank_rate - LAG(bank_rate) OVER (ORDER BY dt) AS delta_pp,
  CASE
    WHEN bank_rate - LAG(bank_rate) OVER (ORDER BY dt) > 0 THEN 'HIKE'
    WHEN bank_rate - LAG(bank_rate) OVER (ORDER BY dt) < 0 THEN 'CUT'
    ELSE 'HOLD'
  END AS regime
FROM daily
ORDER BY dt;

CREATE OR REPLACE VIEW `YOUR_PROJECT.market_data.v_fx_gbpeur` AS
WITH latest AS (
  SELECT *
  FROM `YOUR_PROJECT.market_data.raw_ecb_fx`
  QUALIFY load_ts = MAX(load_ts) OVER ()
),
base AS (
  SELECT
    dt,
    per_eur,
    SAFE_DIVIDE(1.0, per_eur) AS gbp_eur
  FROM latest
  WHERE ccy = 'GBP'
)
SELECT
  dt,
  per_eur,
  gbp_eur,
  LN(gbp_eur) - LN(LAG(gbp_eur) OVER (ORDER BY dt)) AS log_return,
  STDDEV_SAMP(LN(gbp_eur) - LN(LAG(gbp_eur) OVER (ORDER BY dt)))
    OVER (ORDER BY dt ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS vol_20d
FROM base
ORDER BY dt;
