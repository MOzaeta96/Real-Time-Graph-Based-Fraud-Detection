# Real-Time Graph-Based Fraud Detection

A production-style fraud detection platform that simulates e-commerce transactions and processes them through a streaming-inspired machine learning system. This project is designed to demonstrate practical skills across Data Engineering, Machine Learning, and Data Science by combining event-driven ingestion, graph-based feature engineering, model serving, monitoring, and automated retraining.

The system showcases how fraud detection can be implemented in a realistic ML platform setting using:

- **Kafka** for event streaming
- **PostgreSQL** for offline storage and model registry metadata
- **Redis** for online feature serving
- **LightGBM** for fraud scoring
- **FastAPI** for real-time inference
- **Prometheus + Grafana** for observability
- **Champion/Challenger retraining workflows** for model lifecycle management

## What This Project Demonstrates

This repository demonstrates an end-to-end machine learning system for fraud detection, including:

- Event streaming with Kafka
- Streaming-style ingestion into PostgreSQL
- Graph-based fraud feature engineering
- Online feature serving with Redis
- Offline feature storage for training
- LightGBM fraud classification
- Precision–recall model evaluation for extreme class imbalance
- Feature importance visualization (split + gain)
- Prediction and drift monitoring
- Automated retraining workflows with challenger artifacts
- Production-style containerized orchestration with Docker Compose
  
The end-to-end process:
**data ingestion → feature engineering → model training → online feature serving → inference → monitoring → retraining**

It is intentionally designed to reflect the tradeoffs and system boundaries encountered in real fraud detection and MLOps environments.

## Example Fraud Scenario

Transactions can be represented as a graph connecting **users**, **devices**, and **merchants**, as fraud rings often appear as clusters in which multiple accounts share devices or merchants.

Example pattern:

- User A → Device X → Merchant Y  
- User B → Device X → Merchant Y  
- User C → Device X → Merchant Y  

Even if each user appears normal individually, the graph structure, such as the following, can show coordinated activity that the model can use to detect these patterns:

- `max_device_user_degree`
- `avg_merchant_device_degree`

The visualization below shows how users, devices, and merchants connect in a fraud cluster:

![Fraud Graph](docs/fraud_graph_example.png)

## Results Snapshot

Example baseline LightGBM performance from a representative run:

- **ROC AUC:** ~0.61
- **PR AUC:** ~0.0054
- **Precision @ 0.5:** ~0.0058
- **Recall @ 0.5:** ~0.154
- **Best F1 threshold:** ~0.30
- **Threshold achieving ~95% recall:** ~0.003

Because fraud is a highly imbalanced classification problem, precision–recall metrics and threshold policies are emphasized over accuracy.

> Note: exact values will vary slightly depending on generated synthetic data and retraining runs.

## Feature Engineering

Fraud detection benefits heavily from both behavioral and graph-derived features.

### Behavioral Features

The system computes user-level daily aggregates such as:

- `txn_count`
- `total_amount`
- `avg_amount`
- `distinct_merchants`
- `distinct_devices`

These features capture unusual spending behavior, changes in velocity, and shifts in account activity.

### Graph Features

Fraud often involves **shared infrastructure** across accounts. To capture this, the project builds graph-derived features from relationships between:

- Users
- Devices
- Merchants

Example edge types:

- `user ↔ device`
- `user ↔ merchant`
- `device ↔ merchant`

Derived features include:

- `user_device_degree`
- `user_merchant_degree`
- `avg_device_user_degree`
- `max_device_user_degree`
- `avg_merchant_device_degree`
- `max_merchant_device_degree`

These features help identify shared devices, suspicious merchant concentrations, and coordinated fraud-ring behavior.

### Experimental / Extended Features

The feature table also supports additional engineered features for future model iterations, such as:

- `max_amount`
- `amount_spike_ratio`
- `avg_device_fraud_rate`
- `max_device_fraud_rate`

These are currently included in the feature-building pipeline but may not yet be enabled in the baseline model configuration.

## Label Definition

The baseline model is trained to predict whether a user will have at least one fraudulent transaction on the following day.

- **Features:** user-level daily aggregates for day **D**
- **Label:** whether the same user has fraud on day **D + 1**

This framing is more realistic than same-row classification and better reflects proactive fraud risk scoring.

> Note: the feature `had_fraud_today` is intentionally included as an experimental feature because recent fraud activity can be highly predictive in fraud operations. In a strict real-time deployment, this feature would require careful temporal auditing or replacement with a leakage-safe equivalent.

## Model Evaluation

### Feature Importance

The fraud detection model uses both behavioral and graph-derived features.

#### Split Importance
Shows how frequently a feature was used in decision-making.

![Split Importance](docs/feature_importance_split.png)

#### Gain Importance
Shows how much predictive power each feature contributed.

![Gain Importance](docs/feature_importance_gain.png)

### Precision–Recall Curve

The precision–recall curve below is generated on the engineered daily feature table to visualize score separation under class imbalance.

Because fraud detection is a highly imbalanced classification problem, precision–recall is emphasized over accuracy and is often more useful than ROC alone when evaluating operational usefulness.

![Precision-Recall Curve](docs/precision_recall_curve.png)

## Runtime Modes

This project intentionally combines both **streaming-style** and **batch** components:

- **Streaming-style ingestion:** Kafka → `kafka-ingest-consumer` → `raw_transactions`
- **Batch feature computation:** SQL-based daily feature generation and graph aggregates
- **Online serving:** Redis-backed features + FastAPI scoring
- **Batch retraining:** scheduled / controller-driven challenger model generation

This hybrid design reflects how many real production systems evolve before moving to fully streaming feature computation.

## Architecture

```
        +-----------------------+
        | Synthetic Transactions |
        |  Event Generator      |
        +-----------+-----------+
                    |
                    v
               +---------+
               |  Kafka  |
               | Event   |
               | Stream  |
               +----+----+
                    |
                    v
        +--------------------------+
        | kafka-ingest-consumer    |
        | Parse + batch insert     |
        +------------+-------------+
                     |
                     v
            +------------------+
            | PostgreSQL       |
            | raw_transactions |
            +------------------+
                     |
                     v
            +------------------+
            | feature-builder  |
            | Graph Features   |
            +------------------+
                     |
          +----------+-----------+
          v                      v
+----------------+      +------------------+
| Redis          |      | PostgreSQL       |
| Online Feature |      | features table   |
| Store          |      | (training data)  |
+-------+--------+      +---------+--------+
        |                         |
        v                         v
 +--------------+         +----------------+
 | FastAPI      |         | model-training |
 | inference    |         | LightGBM       |
 +------+-------+         +--------+-------+
        |                           |
        v                           v
 +--------------+         +----------------+
 | monitoring   |         | retrain        |
 | prediction   |         | controller     |
 +--------------+         +----------------+
```

## Data Pipeline Flow
```
Synthetic Transactions
        ↓
Kafka Topic (transactions.raw)
        ↓
kafka-ingest-consumer
        ↓
raw_transactions table
        ↓
feature-builder
        ↓
features_user_daily + graph edge tables
        ↓
Redis Online Features
        ↓
FastAPI /score inference
        ↓
Monitoring + Retraining
```

## Tech Stack
### Data Engineering

- Kafka
- PostgreSQL
- Redis
- Python
- SQL
- Docker Compose

### Machine Learning
- LightGBM
- Scikit-learn
- Pandas / NumPy

### Serving / APIs
- FastAPI
- Uvicorn

### Monitoring/MLOps
- Prometheus
- Grafana
- Champion/Challenger model artifacts
- Drift detection
- Prediction monitoring

## Machine Learning
LightGBM is used for fraud classification using behavioral and graph-derived features.

Key model characteristics:
- Handles extreme class imbalance using `scale_pos_weight`
- Optimized for recall to reduce missed fraud
- Evaluated using threshold policies, not just the default 0.5 classification
- Uses both the split and gain feature importance
- Stores drift baseline histograms for downstream monitoring

## Model Operations
The platform includes automated model lifecycle management:
- Champion/Challenger model evaluation
- Challenger artifact generation
- Drift detection using baseline feature histograms
- Prediction score monitoring
- Automatic retraining triggers
- Model registry metadata stored in PostgreSQL
- Model pointer routing for inference

## Repository Structure:
```
Real-Time-Graph-Based-Fraud-Detection
│
├── README.md
├── compose.yaml
│
├── common_fraud/
│   ├── __init__.py
│   └── training/
│       ├── __init__.py
│       └── lgbm_nextday_trainer.py
│
├── data/
│   ├── transactions.parquet
│   └── metadata.json
│
├── docs/
│   ├── fraud_graph_example.png
│   ├── feature_importance_split.png
│   ├── feature_importance_gain.png
│   └── precision_recall_curve.png
│
├── event-generator/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── generator.py
│
├── feature-builder/
│   ├── Dockerfile
│   └── build_features.sql
│
├── feature-publisher/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── publish_latest_to_redis.py
│
├── feature-store/
│   └── schema.sql
│
├── inference-api/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py
│
├── ingestion/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── load_to_postgres.py
│
├── kafka-ingest-consumer/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py
│
├── loadtest/
│   └── load_test.py
│
├── model-training/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── train_lgbm.py
│   ├── artifacts/
│   │   ├── baseline_hist.json
│   │   ├── feature_list.json
│   │   ├── metrics.json
│   │   └── model.joblib
│   ├── artifacts_challenger/
│   │   ├── baseline_hist.json
│   │   ├── feature_list.json
│   │   ├── metrics.json
│   │   └── model.joblib
│   └── runs/
│       └── lgbm_nextday_DATETIME
│
├── monitoring/
│   ├── Dockerfile
│   ├── drift_detector.py
│   ├── validate_dataset.py
│   ├── grafana/
│   │   ├── dashboards/
│   │   │   └── fraud-mlops-dashboard.json
│   │   └── provisioning/
│   │       ├── dashboards/
│   │       │   └── fraud-mlops-dashboard.json
│   │       └── datasources/
│   │           └── datasource.yml
│   └── prometheus/
│       └── prometheus.yml
│
├── notebooks/
│   ├── requirements.txt
│   ├── synthetic_data_generator.py
│   ├── fraud_graph_visualization.py
│   ├── feature_importance_visualization.py
│   └── precision_recall_visualization.py
│
├── prediction-monitor/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── prediction_monitor.py
│
└── retrain-controller/
    ├── Dockerfile
    ├── requirements.txt
    └── retrain_controller.py
```

## Quick Start
### 1) Start infrastructure
```
docker compose up -d postgres redis kafka
```
### 2) Start the Kafka consumer
```
docker compose up -d kafka-ingest-consumer
```
### 3) Generate synthetic transaction events
```
docker compose up event-generator
```
### 4) Verify ingestion
```
docker exec -it fraud-postgres psql -U fraud -d fraud -c "SELECT COUNT(*) FROM raw_transactions;"
```
You should see a non-zero row count (typically around 1,000,000 for the default configuration).
### 5) Build daily + graph features
```
docker compose up feature-builder
```
This step creates / refreshes:
- `features_user_daily`
- `user_device_edges`
- `user_merchant_edges`
- `device_merchant_edges`
> Note: the current feature-building implementation is a full-batch rebuild for clarity and reproducibility, rather than an incremental streaming aggregation job.
### Train the baseline model
```
docker compose up feature-builder
docker compose up model-training
```
This writes baseline artifacts to:
- `model-training/artifacts/model.joblib`
- `model-training/artifacts/metrics.json`
- `model-training/artifacts/feature_list.json`
- `model-training/artifacts/baseline_hist.json`
### 7) Publish latest features to Redis
```
docker compose up publish-latest-features
```
### 8) Start the inference API
```
docker compose up -d inference-api
```
### 9) (Optional) Start monitoring stack
```
docker compose up -d drift-detector prometheus grafana prediction-monitor
```
### 10) (Optional) Start retraining the controller
```
docker compose up -d retrain-controller
```
## Example API Request
### Inference Service & API
The project includes a FastAPI-based real-time inference service that serves fraud risk scores using online features stored in Redis. The API supports:
- Real-time scoring for users and transaction events
- Champion/challenger routing for controlled model rollout
- Shadow evaluation to compare production vs. candidate models safely
- Threshold-based decision policies (f1, recall95, precision20)
- Prometheus metrics for observability
- Redis Streams telemetry for live prediction monitoring

**Default local endpoint:** http://localhost:8000

### Inference Service Overview

- **Framework:** FastAPI
- **Port:** `8000`
- **Online feature store:** Redis
- **Model artifacts:** Mounted under `/models/{champion|challenger}`
- **Supported models:** Champion + Challenger (LightGBM)
- **Routing modes:** `champion`, `challenger`, or `auto`
- **Observability:** Prometheus metrics at `/metrics`
- **Monitoring stream:** Redis Stream (`fraud_predictions`) for live prediction telemetry

## API Endpoints
`GET /health`

Returns service health, Redis connectivity, routing mode, shadow evaluation status, and champion/challenger model load status.
### Example request
```
curl http://localhost:8000/health
```
### Example response
```
{
  "status": "ok",
  "redis_ok": true,
  "ts": "2026-03-11T17:35:23.633962+00:00",
  "model_version": "lgbm_nextday_v2",
  "active_model_mode": "auto",
  "champion_pct": 90,
  "shadow_eval": true,
  "champion_loaded": true,
  "challenger_loaded": true,
  "champion_model_version": "lgbm_nextday_v2",
  "challenger_model_version": "lgbm_nextday_20260306_205512"
}
```
Useful for deployment validation, smoke testing, and verifying that both models are loaded correctly.

---

`POST /score`

Scores a user using the latest online features stored in Redis.

Supports threshold-based policies via the optional `policy` query parameter:
- `f1 (default)`
- `recall95`
- `precision20`

### Example request
```
curl -X POST "http://localhost:8000/score?policy=f1" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "u_4459",
    "amount": 120.5,
    "country": "US"
  }'
```

### Example response
```
audit_id             : 3eea8b9c-a7a8-4a24-9847-8d37b8cc75e1
user_id              : u_4459
fraud_probability    : 0.0
feature_date         :
model_probability    : 0.0
model_version        : lgbm_nextday_v2
policy_used          : f1
threshold_used       : 0.027950120666586968
fraud_decision       : 0
latency_ms           : 31.63
active_model         : champion
bucket               : 35
top_feature_contribs : {@{feature=avg_device_user_degree; contribution=-2.06686513338186}, @{feature=avg_device_fraud_rate; contribution=-1.5470011182990189}, @{feature=max_amount;
                       contribution=-1.0290010304887227}}
bias                 : -10.355717281230477
shadow_eval          : True
shadow               : @{model=challenger; model_version=lgbm_nextday_20260306_205512; fraud_probability=0.002665; model_probability=0.002665; threshold_used=0.5858109170347332; fraud_decision=0}
```
This is the core online inference endpoint for real-time fraud scoring using precomputed online features.

---

`POST /score/transaction`

Scores a transaction event while still leveraging the user’s online Redis features. This is the more production-realistic endpoint for event-driven fraud scoring.

Supports the same optional policy query parameter:

- `f1 (default)`
- `recall95`
- `precision20 `
### Example request
```
curl -X POST "http://localhost:8000/score/transaction?policy=f1" \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "tx_001",
    "user_id": "u_4459",
    "amount": 120.5,
    "country": "US"
  }'
```
### Required fields
- `transaction_id`
- `user_id`
- `amount`
- `country`

### Optional fields
- `timestamp`
- `merchant_id`
- `device_id`

This endpoint more closely mirrors a real payment/fraud decisioning flow, where the service scores incoming transaction events in real time.

---

` GET /model`

Returns detailed metadata for both champion and challenger models, including:

- loaded status
- feature count
- full feature list
- threshold configuration
- artifact paths
- model version

### Example request
```
curl http://localhost:8000/model
```

Useful for debugging model artifacts, verifying feature alignment, and confirming threshold metadata.

---

`GET /model/status`

Returns a lighter-weight operational status view of both models.

Includes:

- loaded status
- model version
- feature count
- default threshold
- policy thresholds

### Example request
```
curl http://localhost:8000/model/status
```

This is the cleaner operational endpoint for dashboards or quick service validation.

---

`GET /routing`

Returns the current champion/challenger routing configuration stored in Redis.

### Example request
```
curl http://localhost:8000/routing
```

### Example response
```
{
  "active_model_mode": "auto",
  "champion_pct": 90
}
```
Makes model traffic routing transparent and easy to inspect during experiments or rollouts.

---

`POST /routing`

Updates the routing configuration without restarting the service.

**Supported modes**
- `champion`
- `challenger`
- `auto`

When using auto, traffic is split deterministically by the user hash bucket.

### Example request
```
curl -X POST http://localhost:8000/routing \
  -H "Content-Type: application/json" \
  -d '{
    "active_model_mode": "auto",
    "champion_pct": 80
  }'
```

Supports controlled traffic ramping and the safe rollout of challengers.

---

`POST /reload-models`

Reloads champion and challenger model artifacts from disk without restarting the API container.

### Example request
```
curl -X POST http://localhost:8000/reload-models
```

Enables lightweight artifact refreshes after new models are promoted or replaced.

---

`GET /shadow/summary`

Summarizes the most recent shadow evaluation events from the Redis Stream.

### Example request
```
curl "http://localhost:8000/shadow/summary?n=200"
```
**What it includes**
- production vs. shadow model counts
- decision mismatch rate
- score delta statistics
- shadow latency statistics

Provides a concise operational summary of how the challenger behaves compared with the production model.

---

`GET /shadow/gate`

Evaluates whether the challenger passes promotion guardrails based on recent shadow events.

**Guardrails include**
- decision mismatch rate
- p99 shadow latency
- p99 score drift

### Example request
```
curl "http://localhost:8000/shadow/gate?n=200"
```

Implements a simple but realistic promotion gate before shifting more traffic to the challenger.

---

`POST /shadow/promote`

Returns a recommendation to:
- `HOLD`
- `RAMP`
based on the shadow gate results and minimum event thresholds.

### Example request
```
curl -X POST "http://localhost:8000/shadow/promote?n=2000&step=20&min_events=200"
```

Simulates a production-safe promotion workflow for gradually increasing challenger traffic.

---

`GET /metrics`

Exposes Prometheus metrics for the inference service.

### Example request
```
curl http://localhost:8000/metrics
```
**Metrics include**
- request counts
- request latency histograms
- fraud decision counts
- shadow prediction counts
- shadow latency histograms
- prediction score distributions
- model reload counters

This endpoint powers Prometheus/Grafana observability for the online inference service.

---

## Reproducing Visualizations
After feature generation and model training, the visualization scripts can be run locally from the repo root.
```
python notebooks/fraud_graph_visualization.py
python notebooks/feature_importance_visualization.py
python notebooks/precision_recall_visualization.py
```
Generated outputs:
- `docs/fraud_graph_example.png`
- `docs/feature_importance_split.png`
- `docs/feature_importance_gain.png`
- `docs/precision_recall_curve.png`

## Model Training & Promotion Strategy

This repository separates model development from model serving.

### Training / Offline Evaluation
- Train LightGBM models on historical fraud data
- Evaluate offline metrics (AUC, PR AUC, F1, threshold selection)
- Persist artifacts:
  - `model.joblib`
  - `feature_list.json`
  - `metrics.json`

### Champion / Challenger Serving
- Champion serves the majority of production traffic
- Challenger receives either:
  - direct routed traffic (in `auto` mode)
  - or shadow-only comparisons

### Promotion Guardrails
The API includes a lightweight promotion framework:

- `/shadow/summary` → recent challenger comparison stats
- `/shadow/gate` → promotion safety checks
- `/shadow/promote` → recommendation to `HOLD` or `RAMP`

This mirrors a real production model governance workflow.

## Current Limitations
This project is intentionally designed as a production-style demonstration, but several components are simplified relative to a fully hardened deployment:
- The synthetic data generator produces realistic but simulated fraud patterns rather than true production behavior.
- Feature engineering is currently batch-oriented at the daily user level, rather than fully streaming per-event feature aggregation.
- The precision–recall visualization is generated from the engineered feature table for interpretability, not as a formal held-out benchmark artifact.
- PostgreSQL is used as a lightweight model registry for simplicity instead of a dedicated registry service such as MLflow.
- Some extended engineered features are present in the feature table but not yet enabled in the baseline LightGBM configuration.

## Production Risks to Address
This project intentionally highlights several real-world production concerns:
- **Data leakage controls:** Features such as same-day fraud indicators can be useful for experimentation, but must be carefully audited to avoid leakage in true real-time scoring.
- **Feature freshness:** Online Redis features and offline PostgreSQL features should be validated for consistency and staleness.
- **Schema evolution:** Kafka message contracts should be versioned to prevent breaking downstream consumers.
- **Backfill/replay safety:** Ingestion should support idempotent reprocessing and safe offset management.
- **Model degradation:** Prediction drift and feature distribution drift should be continuously monitored and tied to retraining policies.
- **Class imbalance:** Fraud prevalence is extremely low, so threshold tuning and alert-volume controls are critical for operational usefulness.
- **Graph feature explosion:** High-cardinality user/device/merchant relationships can grow rapidly and may require pruning, windowing, or approximate graph statistics at a larger scale.

## Scaling Path to Production
If extended into a larger-scale deployment, I would evolve this system by:
* Replacing batch feature generation with Kafka Streams, Spark Structured Streaming, or Apache Flink
- Adding Avro/Protobuf + Schema Registry for Kafka contracts
- Introducing online/offline feature parity tests
- Moving model registry responsibilities to MLflow or a dedicated metadata service
- Implementing cost-sensitive threshold optimization based on fraud loss assumptions and analyst capacity
- Adding incremental graph feature maintenance or approximate graph statistics for high-scale operation

## Future Improvements
Planned or potential extensions include:
- Node2Vec or graph embedding features for fraud ring detection
- MLflow model registry integration
- Streaming feature computation
- Stronger online model evaluation
- More realistic synthetic fraud scenarios
- Cost-based decision policies for fraud review queues
- More sophisticated drift alerting and dashboarding
