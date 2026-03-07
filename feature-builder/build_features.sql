-- Build daily per-user features + edge tables from raw_transactions

TRUNCATE TABLE features_user_daily;

INSERT INTO features_user_daily (
  feature_date,
  user_id,
  txn_count,
  total_amount,
  avg_amount,
  distinct_merchants,
  distinct_devices,
  fraud_txn_count,
  fraud_rate
)
SELECT
  rt."timestamp"::date AS feature_date,
  rt.user_id,
  COUNT(*)::int AS txn_count,
  COALESCE(SUM(rt.amount), 0)::double precision AS total_amount,
  COALESCE(AVG(rt.amount), 0)::double precision AS avg_amount,
  COUNT(DISTINCT rt.merchant_id)::int AS distinct_merchants,
  COUNT(DISTINCT rt.device_id)::int AS distinct_devices,
  SUM(CASE WHEN rt.is_fraud = 1 THEN 1 ELSE 0 END)::int AS fraud_txn_count,
  (SUM(CASE WHEN rt.is_fraud = 1 THEN 1 ELSE 0 END)::double precision / COUNT(*)::double precision) AS fraud_rate
FROM raw_transactions rt
GROUP BY 1, 2;

CREATE INDEX IF NOT EXISTS idx_features_user_daily_user_date
ON features_user_daily (user_id, feature_date);

CREATE INDEX IF NOT EXISTS idx_features_user_daily_date
ON features_user_daily (feature_date);

-- Edges (schema is just pairs)
TRUNCATE TABLE user_device_edges;
INSERT INTO user_device_edges (user_id, device_id)
SELECT DISTINCT user_id, device_id
FROM raw_transactions;

TRUNCATE TABLE user_merchant_edges;
INSERT INTO user_merchant_edges (user_id, merchant_id)
SELECT DISTINCT user_id, merchant_id
FROM raw_transactions;

TRUNCATE TABLE device_merchant_edges;
INSERT INTO device_merchant_edges (device_id, merchant_id)
SELECT DISTINCT device_id, merchant_id
FROM raw_transactions;

-- Graph features (per user)

-- Features

-- device -> how many users used it
DROP TABLE IF EXISTS tmp_device_user_degree;
CREATE TEMP TABLE tmp_device_user_degree AS
SELECT device_id, COUNT(*)::int AS device_user_degree
FROM user_device_edges
GROUP BY device_id;

-- merchant -> how many devices used it
DROP TABLE IF EXISTS tmp_merchant_device_degree;
CREATE TEMP TABLE tmp_merchant_device_degree AS
SELECT merchant_id, COUNT(*)::int AS merchant_device_degree
FROM device_merchant_edges
GROUP BY merchant_id;

-- per-user graph features in one table
DROP TABLE IF EXISTS tmp_user_graph;
CREATE TEMP TABLE tmp_user_graph AS
SELECT
  u.user_id,

  -- degrees
  COALESCE(ud.user_device_degree, 0) AS user_device_degree,
  COALESCE(um.user_merchant_degree, 0) AS user_merchant_degree,

  -- shared-device risk (avg/max users per device for user's devices)
  COALESCE(udr.avg_device_user_degree, 0)::double precision AS avg_device_user_degree,
  COALESCE(udr.max_device_user_degree, 0) AS max_device_user_degree,

  -- merchant crowding (avg/max devices per merchant for user's merchants)
  COALESCE(umr.avg_merchant_device_degree, 0)::double precision AS avg_merchant_device_degree,
  COALESCE(umr.max_merchant_device_degree, 0) AS max_merchant_device_degree

FROM
  (SELECT DISTINCT user_id FROM features_user_daily) u

LEFT JOIN (
  SELECT user_id, COUNT(*)::int AS user_device_degree
  FROM user_device_edges
  GROUP BY user_id
) ud ON ud.user_id = u.user_id

LEFT JOIN (
  SELECT user_id, COUNT(*)::int AS user_merchant_degree
  FROM user_merchant_edges
  GROUP BY user_id
) um ON um.user_id = u.user_id

LEFT JOIN (
  SELECT
    ude.user_id,
    AVG(dud.device_user_degree)::double precision AS avg_device_user_degree,
    MAX(dud.device_user_degree)::int AS max_device_user_degree
  FROM user_device_edges ude
  JOIN tmp_device_user_degree dud ON dud.device_id = ude.device_id
  GROUP BY ude.user_id
) udr ON udr.user_id = u.user_id

LEFT JOIN (
  SELECT
    ume.user_id,
    AVG(mdd.merchant_device_degree)::double precision AS avg_merchant_device_degree,
    MAX(mdd.merchant_device_degree)::int AS max_merchant_device_degree
  FROM user_merchant_edges ume
  JOIN tmp_merchant_device_degree mdd ON mdd.merchant_id = ume.merchant_id
  GROUP BY ume.user_id
) umr ON umr.user_id = u.user_id;

-- apply to all user-day rows
UPDATE features_user_daily f
SET
  user_device_degree = g.user_device_degree,
  user_merchant_degree = g.user_merchant_degree,
  avg_device_user_degree = g.avg_device_user_degree,
  max_device_user_degree = g.max_device_user_degree,
  avg_merchant_device_degree = g.avg_merchant_device_degree,
  max_merchant_device_degree = g.max_merchant_device_degree
FROM tmp_user_graph g
WHERE f.user_id = g.user_id;