# Real-Time Graph-Based Fraud Detection
This project aims to replicate a production-style fraud detection platform by simulating e-commerce transactions and processing them through a streaming-style ML system.
The platform demonstrates how fraud detection models operate in a realistic production environment by combining event-driven ingestion, offline and online feature storage, model serving, monitoring, and automated retraining.
This project focuses on overall system design for Machine Learning, and not just model training.

## What This Project Demonstrates

This repository demonstrates an end-to-end machine learning system for fraud detection, including:

- Event streaming with Kafka
- Real-time feature pipelines
- Graph-based fraud feature engineering
- Online feature serving with Redis
- Offline storage with PostgreSQL
- LightGBM fraud classification
- Precision–recall model evaluation
- Feature importance visualization
- Model drift monitoring
- Automated retraining workflows

## Example Fraud Scenario

Transactions can be represented as a graph connecting users, devices, and merchants.

Fraud rings often appear as clusters where multiple accounts share devices or merchants.

Example pattern:

User A → Device X → Merchant Y  
User B → Device X → Merchant Y  
User C → Device X → Merchant Y  

Even if each user appears normal individually, the graph structure reveals coordinated activity.

Graph features such as those below allow the model to detect these patterns.:

- `max_device_user_degree`
- `avg_merchant_device_degree`

The visualization below shows how users, devices, and merchants connect in a fraud cluster:

![Fraud Graph](docs/fraud_graph_example.png)

## Feature Importance

The fraud detection model uses behavioral and graph-derived features.

### Split Importance
Shows how frequently a feature was used in decision-making.

![Split Importance](docs/feature_importance_split.png)

### Gain Importance
Shows how much predictive power each feature contributed.

![Gain Importance](docs/feature_importance_gain.png)

## Precision-Recall Curve

The precision-recall curve below is generated on the engineered daily feature table to visualize score separation under class imbalance. Because fraud detection is a highly imbalanced classification problem, precision–recall is used to assess model performance, rather than accuracy or ROC.

![Precision-Recall Curve](docs/precision_recall_curve.png)

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
Consumer Batch Inserts
        ↓
raw_transactions table
        ↓
Feature Engineering
        ↓
Feature Tables
        ↓
Redis Online Features
```

## Tech Stack
### Data Engineering:
- Kafka
- PostgreSQL
- Redis
- Python
- Docker Compose

## Machine Learning

LightGBM is used for fraud classification using behavioral and graph-derived features.

Key model characteristics:

- Handles extreme class imbalance using `scale_pos_weight`
- Optimized for recall to minimize missed fraud
- Feature importance analysis using both split and gain metrics
- Precision–recall evaluation for imbalanced classification problems


## Model Operations

The platform includes automated model lifecycle management:

- Champion/challenger model evaluation
- Drift detection using baseline feature histograms
- Automatic retraining triggers
- Model registry stored in PostgreSQL

### Monitoring:
- Dataset validation checks
- Observability via logs and metrics

## Repository Structure:
```
Real-Time-Graph-Based-Fraud-Detection
│
├── compose.yaml
│
├── common_fraud/
|   ├── training/
|   |   ├── __init__.py
│   |   └── lgbm_nextday_trainer.py
|   └── __init___.py
|
├── data/
│   ├── transactions.parquet
│   └── metadata.json
|
├── docs/
|   ├── feature_importance_split.png
|   ├── feature_importance_gain.png
│   └── fraud_graph_example.png
│
├── event-generator/
|   ├── Dockerfile
|   ├── requirements.txt
│   └── generator.py
│
├── feature-builder/
|   ├── Dockerfile
│   └── build_features.sql
│
├── feature-publisher/
|   ├── Dockerfile
|   ├── requirements.txt
│   └── publish_latest_to_redis.py
|
├── feature-store/
│   └── schema.sql
│
├── inference-api/
|   ├── Dockerfile
|   ├── requirements.txt
│   └── main.py
|
├── ingestion/
|   ├── Dockerfile
|   ├── requirements.txt
│   └── load_to_postgres.py
|
├── kafka-ingest-consumer/
|   ├── Dockerfile
|   ├── requirements.txt
│   └── main.py
│
├── loadtest/
│   └── load_test.py
|
├── model-training/
│   ├── train_lgbm.py
|   ├── Dockerfile
|   ├── requirements.txt
│   ├── artifacts/
|   |   ├── baseline_hist.json
|   |   ├── feature_list.json
|   |   ├── metrics.json
|   |   └── model.joblib
|   |
│   ├── artifacts_challenger/
|   |   ├── baseline_hist.json
|   |   ├── feature_list.json
|   |   ├── metrics.json
|   |   └── model.joblib
|   |
|   └── runs/
|       └── lgbm_nextday_DATETIME
|
├── monitoring/
|   ├── Dockerfile
|   ├── drift_detector.py
│   ├── validate_dataset.py
│   ├── grafana/
|   |   ├── dashboards/
|   |   |    └── fraud-mlops-dashboard.json
|   |   |
|   |   └── provisioning/
|   |       ├── dashboards/
|   |       |    └── fraud-mlops-dashboard.json
|   |       |
|   |       └── datasources/
|   |           └── datasource.yml
|   |
│   └── prometheus/
|       ├── prometheus.yml
|       └── data/
|           ├── queries.active
|           ├── chunks_head/
|           |
|           └── wal/
|               └── 00000000
|           
|
├── notebooks/
|    ├── requirements.txt
|    ├── fraud_graph_visualization.py
|    └── synthetic_data_generator.py
|
├── prediction-monitor/
|    └── prediction_monitor.py
|
└── retain-controller
    ├── retrain_controller.py
    ├── Dockerfile
    └── requirements.txt
```

## Quick Start
### Start infrastructure:
```
docker compose up -d postgres redis kafka
```

### Start the Kafka consumer:
```
docker compose up kafka-ingest-consumer
```

### Generate synthetic transaction events:
```
docker compose up event-generator
```

### Verify data ingestion:
```
docker exec -it fraud-postgres psql -U fraud -d fraud -c "SELECT COUNT(*) FROM raw_transactions;"
```

### Train the model:
```
docker compose up model-training
```

### Publish features to Redis:
```
docker compose up publish-latest-features
```

### Start the inference API:
```
docker compose up -d inference-api
```

### Example API Request:
```
POST /score
```

### Example request body:
```
{
  "user_id": "u_123",
  "amount": 45.20,
  "country": "US"
}
```
The API returns a fraud probability and model metadata.

## Current Limitations
This project focuses on demonstrating the architecture of a fraud detection platform.
Some components are simplified:
- Feature computation is batch-based rather than fully streaming
- Graph features are aggregate metrics rather than learned embeddings
- Model registry integration is not yet implemented
- Synthetic data is used instead of real financial data

## Future Improvements
Planned extensions:
- Node2Vec graph embeddings for fraud rings
- MLflow model registry integration
- Streaming feature computation
- Drift monitoring dashboards
- Online model evaluation

## Why This Project Matters
While most ML portfolio projects only show model training in notebooks, this project demonstrates the full lifecycle of a production ML system:

data ingestion → feature engineering → model training → inference → monitoring → retraining

Through this project, I aim to showcase system design skills critical to Data Science, Machine Learning Engineering, and Data Engineering roles and to test my proficiency in each.

