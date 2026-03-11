import json
import os
import joblib
import matplotlib.pyplot as plt
import pandas as pd

from sklearn.metrics import average_precision_score, precision_recall_curve
from sqlalchemy import create_engine


DB_URI = "postgresql://fraud:fraud@localhost:5432/fraud"
SAMPLE_SIZE = 10000

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.dirname(script_dir)
docs_dir = os.path.join(repo_root, "docs")
os.makedirs(docs_dir, exist_ok=True)

model_path = os.path.join(repo_root, "model-training", "artifacts", "model.joblib")
feature_list_path = os.path.join(repo_root, "model-training", "artifacts", "feature_list.json")

pr_output_path = os.path.join(docs_dir, "precision_recall_curve.png")
roc_output_path = os.path.join(docs_dir, "roc_curve.png")

# Load model + features
model = joblib.load(model_path)

with open(feature_list_path, "r", encoding="utf-8") as f:
    feature_list = json.load(f)

print("Model loaded.")
print("Feature count:", len(feature_list))


# Load feature rows
engine = create_engine(DB_URI)

query = f"""
SELECT *
FROM features_user_daily
LIMIT {SAMPLE_SIZE};
"""

df = pd.read_sql(query, engine)

if df.empty:
    raise RuntimeError(
        "features_user_daily contains 0 rows. Run `docker compose up feature-builder` first."
    )

# Compatibility-derived feature used by current model
if "fraud_txn_count" not in df.columns:
    raise RuntimeError("features_user_daily is missing fraud_txn_count.")

if "had_fraud_today" in feature_list and "had_fraud_today" not in df.columns:
    df["had_fraud_today"] = (df["fraud_txn_count"] > 0).astype(int)

missing_features = [c for c in feature_list if c not in df.columns]
if missing_features:
    raise RuntimeError(f"Missing required model features: {missing_features}")

# Daily label proxy for visualization
df["label"] = (df["fraud_txn_count"] > 0).astype(int)

X = df[feature_list].astype(float)
y = df["label"].astype(int)

if y.nunique() < 2:
    raise RuntimeError("Need both positive and negative rows to draw a PR curve.")


# Score
scores = model.predict_proba(X)[:, 1]

precision, recall, _ = precision_recall_curve(y, scores)
pr_auc = average_precision_score(y, scores)

print(f"Rows loaded: {len(df)}")
print(f"Fraud rows: {(y == 1).sum()}")
print(f"Non-fraud rows: {(y == 0).sum()}")
print(f"Average precision (PR AUC): {pr_auc:.4f}")

# Plot PR curve
plt.figure(figsize=(8, 6))
plt.plot(recall, precision, label=f"PR AUC = {pr_auc:.4f}")
plt.xlabel("Recall")
plt.ylabel("Precision")
plt.title("Precision-Recall Curve")
plt.legend()
plt.tight_layout()
plt.savefig(pr_output_path, dpi=300, bbox_inches="tight")
plt.show()

print(f"Precision-recall curve saved to: {pr_output_path}")
