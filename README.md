# Real-Time-Graph-Based-Fraud-Detection
Simulating a payment ecosystem to attempt to find instances of fraud using dynamic graphs and anomaly detection, designed to be cloud-agnostic and portable between AWS and local environments using containerized services.

This project will use Docker Containers for the following:
Kafka - Event backbone
Python event generator
Python (or Spark) consumer
Redis - Online feature storage
PostgreSQL - Offline feature storage
MLflow - Model registry
Batch container for model training
FastAPI Inference Service

Example Architecture:
```
                        ┌─────────────────────┐
                        │   Event Generator   │
                        └──────────┬──────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │        Kafka        │
                        └──────────┬──────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │ Streaming Processor │
                        └──────────┬──────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
               Redis         PostgreSQL        S3/Local FS
             (Online)         (Offline)        (Raw storage)
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │    Model Training   │
                        └──────────┬──────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │       MLflow        │
                        └──────────┬──────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │     FastAPI API     │
                        └─────────────────────┘
```
Example Repository Structure:
```
fraud-detection-platform/
│
├── README.md
├── LICENSE
├── .env.example
├── docker-compose.yml
├── requirements.txt
│
├── docs/
│   ├── architecture.md
│   ├── er-diagram.png
│   ├── system-design.png
│   └── data-dictionary.md
│
├── infrastructure/
│   ├── aws-setup.md
│   └── terraform/         
│
├── event-generator/
│   ├── Dockerfile
│   ├── generator.py
│   └── config.py
│
├── streaming/
│   ├── Dockerfile
│   ├── consumer.py
│   ├── feature_engineering.py
│   └── utils.py
│
├── feature-store/
│   ├── redis_client.py
│   ├── postgres_client.py
│   └── schema.sql
│
├── model-training/
│   ├── Dockerfile
│   ├── train.py
│   ├── evaluate.py
│   └── features.py
│
├── inference-api/
│   ├── Dockerfile
│   ├── main.py
│   ├── model_loader.py
│   └── schemas.py
│
├── monitoring/
|   ├── validate_dataset.py
│   ├── drift_detection.py
│   └── metrics.py
│
└── notebooks/
    ├── 01_data_simulation.ipynb
    ├── 02_eda.ipynb
    └── 03_model_experiments.ipynb
```



Current Repo:
```
Real-Time-Graph-Based-Fraud-Detection
│
├── compose.yaml
│
├── data/
│   ├── transactions.parquet
│   ├── metadata.json
│   └── qa_report.json
│
├── event-generator/
│   └── generator.py
│
├── ingestion/
│   └── load_to_postgres.py
│
├── feature-store/
│   └── schema.sql
│
├── feature-publisher/
│   └── publish_latest_to_redis.py
│
├── inference-api/
│   └── main.py
│
├── model-training/
│   ├── train_lgbm.py
│   └── artifacts/
│
├── loadtest/
│   └── load_test.py
│
├── monitoring/
│   └── validate_dataset.py
│
└── notebooks/
    └── synthetic_data_generator.py
```
