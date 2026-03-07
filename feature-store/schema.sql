CREATE TABLE IF NOT EXISTS raw_transactions (
    transaction_id TEXT PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    user_id TEXT NOT NULL,
    merchant_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    amount DOUBLE PRECISION NOT NULL,
    country TEXT NOT NULL,
    is_fraud INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS user_device_edges (
  user_id TEXT NOT NULL,
  device_id TEXT NOT NULL,
  PRIMARY KEY (user_id, device_id)
);

CREATE TABLE IF NOT EXISTS user_merchant_edges (
  user_id TEXT NOT NULL,
  merchant_id TEXT NOT NULL,
  PRIMARY KEY (user_id, merchant_id)
);

CREATE TABLE IF NOT EXISTS device_merchant_edges (
  device_id TEXT NOT NULL,
  merchant_id TEXT NOT NULL,
  PRIMARY KEY (device_id, merchant_id)
);

CREATE TABLE IF NOT EXISTS features_user_daily (
  feature_date DATE NOT NULL,
  user_id TEXT NOT NULL,

  txn_count INTEGER NOT NULL,
  total_amount DOUBLE PRECISION NOT NULL,
  avg_amount DOUBLE PRECISION NOT NULL,
  distinct_merchants INTEGER NOT NULL,
  distinct_devices INTEGER NOT NULL,

  fraud_txn_count INTEGER NOT NULL,
  fraud_rate DOUBLE PRECISION NOT NULL,

  PRIMARY KEY (feature_date, user_id)
);

ALTER TABLE features_user_daily
  ADD COLUMN IF NOT EXISTS user_device_degree INT,
  ADD COLUMN IF NOT EXISTS user_merchant_degree INT,
  ADD COLUMN IF NOT EXISTS avg_device_user_degree DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS max_device_user_degree INT,
  ADD COLUMN IF NOT EXISTS avg_merchant_device_degree DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS max_merchant_device_degree INT;

CREATE TABLE IF NOT EXISTS model_registry (
  model_version TEXT PRIMARY KEY,
  trained_at_utc TIMESTAMPTZ NOT NULL,
  data_window_start DATE,
  data_window_end DATE,
  train_rows BIGINT,
  auc DOUBLE PRECISION,
  pr_auc DOUBLE PRECISION,
  logloss DOUBLE PRECISION,
  artifact_path TEXT NOT NULL,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS model_pointers (
  name TEXT PRIMARY KEY,            -- 'champion' | 'challenger' | 'last_good'
  model_version TEXT NOT NULL,
  updated_at_utc TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_id ON raw_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_device_id ON raw_transactions(device_id);
CREATE INDEX IF NOT EXISTS idx_merchant_id ON raw_transactions(merchant_id);
CREATE INDEX IF NOT EXISTS idx_timestamp ON raw_transactions(timestamp);
CREATE INDEX IF NOT EXISTS idx_udev_device ON user_device_edges(device_id);
CREATE INDEX IF NOT EXISTS idx_umerch_merchant ON user_merchant_edges(merchant_id);
CREATE INDEX IF NOT EXISTS idx_dmerch_merchant ON device_merchant_edges(merchant_id);
CREATE INDEX IF NOT EXISTS idx_features_user_daily_user ON features_user_daily(user_id);
CREATE INDEX IF NOT EXISTS idx_features_user_daily_date ON features_user_daily(feature_date);