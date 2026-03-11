import json
import numpy as np
import os
import pandas as pd
import psycopg2
import time

from datetime import datetime, timezone
from prometheus_client import Gauge, Counter, start_http_server

PGHOST = os.getenv("PGHOST", "postgres")
PGPORT = int(os.getenv("PGPORT", "5432"))
PGDATABASE = os.getenv("PGDATABASE", "fraud")
PGUSER = os.getenv("PGUSER", "fraud")
PGPASSWORD = os.getenv("PGPASSWORD", "fraud")

# Baseline histogram file created by training (mounted into the container).
BASELINE_PATH = os.getenv("BASELINE_PATH", "/models/champion/baseline_hist.json")

# Drift window: compare last N days to baseline.
DRIFT_WINDOW_DAYS = int(os.getenv("DRIFT_WINDOW_DAYS", "3"))
DRIFT_INTERVAL_SEC = int(os.getenv("DRIFT_INTERVAL_SEC", "300"))

# PSI thresholds (common heuristics)
PSI_WARN = float(os.getenv("PSI_WARN", "0.10"))
PSI_ALERT = float(os.getenv("PSI_ALERT", "0.20"))

DRIFT_RUNS_TOTAL = Counter(
    "drift_detector_runs_total",
    "Total number of drift detector runs",
)

DRIFT_RUN_LAST_TS = Gauge(
    "drift_detector_last_run_timestamp",
    "Unix timestamp of the last drift detector run",
)

DRIFT_FEATURES_TOTAL = Gauge(
    "drift_features_total",
    "Count of features by drift status",
    ["status"],  # OK|WARN|ALERT
)

DRIFT_PSI = Gauge(
    "feature_psi",
    "PSI value for a feature over the current window",
    ["feature"],
)

DRIFT_BASELINE_MISSING = Gauge(
    "drift_baseline_missing",
    "1 if baseline histogram file missing/unreadable, else 0",
)

DRIFT_DB_OK = Gauge(
    "drift_db_ok",
    "1 if DB connection succeeded in last run, else 0",
)

DDL = """
CREATE TABLE IF NOT EXISTS drift_reports (
  id BIGSERIAL PRIMARY KEY,
  generated_at_utc TIMESTAMPTZ NOT NULL,
  window_start DATE NOT NULL,
  window_end DATE NOT NULL,
  baseline_model_version TEXT,
  feature_name TEXT NOT NULL,
  psi DOUBLE PRECISION NOT NULL,
  status TEXT NOT NULL,
  expected_bins JSONB,
  actual_bins JSONB
);

CREATE INDEX IF NOT EXISTS idx_drift_reports_generated_at ON drift_reports(generated_at_utc);
CREATE INDEX IF NOT EXISTS idx_drift_reports_feature ON drift_reports(feature_name);
"""


def _connect():
    return psycopg2.connect(
        host=PGHOST,
        port=PGPORT,
        dbname=PGDATABASE,
        user=PGUSER,
        password=PGPASSWORD,
    )


def _load_baseline() -> dict:
    if not os.path.exists(BASELINE_PATH):
        raise FileNotFoundError(
            f"Baseline histogram file not found at {BASELINE_PATH}. "
            "Run training to generate artifacts/baseline_hist.json or mount it into /models/champion."
        )
    with open(BASELINE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _psi(expected: np.ndarray, actual: np.ndarray, eps: float = 1e-6) -> float:
    """Population Stability Index.

    expected and actual are proportions (sum to 1). eps prevents division by zero.
    """
    e = np.clip(expected.astype(float), eps, 1.0)
    a = np.clip(actual.astype(float), eps, 1.0)
    return float(np.sum((a - e) * np.log(a / e)))


def _status(psi_val: float) -> str:
    if psi_val >= PSI_ALERT:
        return "ALERT"
    if psi_val >= PSI_WARN:
        return "WARN"
    return "OK"


def _get_window(conn) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Compute drift window based on latest feature_date in warehouse."""
    df = pd.read_sql("SELECT MAX(feature_date) AS max_d FROM features_user_daily", conn)
    max_d = df.loc[0, "max_d"]
    if pd.isna(max_d):
        raise RuntimeError("No rows found in features_user_daily. Run ingestion + feature generation first.")

    end = pd.to_datetime(max_d).date()
    start = (pd.to_datetime(max_d) - pd.Timedelta(days=DRIFT_WINDOW_DAYS - 1)).date()
    return start, end


def _load_recent_features(conn, features: list[str], window_start, window_end) -> pd.DataFrame:
    cols = ",".join(["feature_date"] + [f"{c}" for c in features])
    q = f"""
    SELECT {cols}
    FROM features_user_daily
    WHERE feature_date >= %s AND feature_date <= %s
    """
    return pd.read_sql(q, conn, params=(window_start, window_end))


def _reset_run_gauges():
    """Reset gauges that should represent only the most recent run."""
    # Clear feature_psi labelset so old features/labels don't linger if feature list changes.
    DRIFT_PSI.clear()

    # Set all statuses to 0; then we'll set real counts.
    DRIFT_FEATURES_TOTAL.labels(status="OK").set(0)
    DRIFT_FEATURES_TOTAL.labels(status="WARN").set(0)
    DRIFT_FEATURES_TOTAL.labels(status="ALERT").set(0)


def run_once():
    """
    One drift detection run:
      - load baseline hist
      - query recent window from Postgres
      - compute PSI per feature
      - write results to drift_reports
      - export Prometheus metrics
    """
    DRIFT_RUNS_TOTAL.inc()
    DRIFT_RUN_LAST_TS.set(time.time())
    _reset_run_gauges()

    # Baseline load + baseline-missing metric
    try:
        baseline = _load_baseline()
        DRIFT_BASELINE_MISSING.set(0)
    except Exception:
        DRIFT_BASELINE_MISSING.set(1)
        raise

    b_features = baseline.get("features", {})
    feature_names = sorted(b_features.keys())
    baseline_model_version = baseline.get("model_version")

    # Connect to DB and set db_ok appropriately
    conn = None
    try:
        conn = _connect()
        DRIFT_DB_OK.set(1)
    except Exception:
        DRIFT_DB_OK.set(0)
        raise

    try:
        with conn.cursor() as cur:
            cur.execute(DDL)
            conn.commit()

        window_start, window_end = _get_window(conn)

        # Load data
        df = _load_recent_features(conn, feature_names, window_start, window_end)
        if df.empty:
            raise RuntimeError("No rows found in drift window; cannot compute drift.")

        generated_at_utc = datetime.now(timezone.utc).isoformat()

        rows_to_insert = []
        ok_count = 0
        warn_count = 0
        alert_count = 0

        for f in feature_names:
            # Skip if feature missing (schema drift)
            if f not in df.columns:
                # You could also insert a special status row if you want.
                continue

            edges = np.asarray(b_features[f]["edges"], dtype=float)
            expected = np.asarray(b_features[f]["expected"], dtype=float)

            # Handle NaNs defensively
            if f in df.columns:
                arr = df[f].astype(float).to_numpy()
            elif f == "had_fraud_today" and "fraud_txn_count" in df.columns:
                arr = (df["fraud_txn_count"].astype(float) > 0).astype(float).to_numpy()
            else:
                # skip features we can't compute from the warehouse
                continue
            arr = arr[~np.isnan(arr)]
            if arr.size == 0:
                # No valid values in window: treat as max drift or skip. We'll skip and not set PSI.
                continue

            counts, _ = np.histogram(arr, bins=edges)
            total = float(np.sum(counts)) if np.sum(counts) else 1.0
            actual = (counts / total).astype(float)

            psi_val = _psi(expected, actual)
            st = _status(psi_val)

            # Prometheus per-feature PSI
            DRIFT_PSI.labels(feature=f).set(float(psi_val))

            if st == "OK":
                ok_count += 1
            elif st == "WARN":
                warn_count += 1
            else:
                alert_count += 1

            rows_to_insert.append(
                (
                    generated_at_utc,
                    window_start,
                    window_end,
                    baseline_model_version,
                    f,
                    psi_val,
                    st,
                    json.dumps(expected.tolist()),
                    json.dumps(actual.tolist()),
                )
            )

        # Update aggregate drift counts (Prometheus)
        DRIFT_FEATURES_TOTAL.labels(status="OK").set(ok_count)
        DRIFT_FEATURES_TOTAL.labels(status="WARN").set(warn_count)
        DRIFT_FEATURES_TOTAL.labels(status="ALERT").set(alert_count)

        # Persist results
        if rows_to_insert:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO drift_reports (
                      generated_at_utc, window_start, window_end, baseline_model_version,
                      feature_name, psi, status, expected_bins, actual_bins
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
                    """,
                    rows_to_insert,
                )
                conn.commit()

        print(
            f"[drift] {generated_at_utc} window=[{window_start},{window_end}] "
            f"ok={ok_count} warn={warn_count} alert={alert_count} baseline={baseline_model_version}"
        )

    finally:
        if conn is not None:
            conn.close()


def main():
    METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))
    start_http_server(METRICS_PORT)  # serves /metrics

    while True:
        try:
            run_once()
        except Exception as e:
            # If DB breaks mid-run, mark it down for observability
            # (baseline missing is already set in baseline loader failure path)
            DRIFT_DB_OK.set(0)
            print(f"[drift] ERROR: {e}")
        time.sleep(DRIFT_INTERVAL_SEC)


if __name__ == "__main__":
    main()
