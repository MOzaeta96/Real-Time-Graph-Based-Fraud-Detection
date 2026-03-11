import os
import json
import joblib
import matplotlib.pyplot as plt
import pandas as pd

from sqlalchemy import create_engine

# Config
DB_URI = "postgresql://fraud:fraud@localhost:5432/fraud"
SAMPLE_SIZE = 5000

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.dirname(script_dir)
docs_dir = os.path.join(repo_root, "docs")
os.makedirs(docs_dir, exist_ok=True)

model_path = os.path.join(repo_root, "model-training", "artifacts", "model.joblib")
feature_list_path = os.path.join(repo_root, "model-training", "artifacts", "feature_list.json")

output_path = os.path.join(docs_dir, "fraud_score_distribution.png")

# Load model + feature list
model = joblib.load(model_path)

with open(feature_list_path, "r", encoding="utf-8") as f:
    feature_list = json.load(f)

print("Model loaded.")
print("Feature count:", len(feature_list))

# Load feature dataset sample
engine = create_engine(DB_URI)

query = f"""
SELECT *
FROM features_user_daily
LIMIT {SAMPLE_SIZE};
"""

df = pd.read_sql(query, engine)

if df.empty:
    raise RuntimeError(
        "No rows found in features_user_daily. Run feature-builder first."
    )

if "fraud_txn_count" not in df.columns:
    raise RuntimeError("features_user_daily is missing fraud_txn_count, so a label cannot be derived.")

# Derive compatibility feature expected by the trained model
df["had_fraud_today"] = (df["fraud_txn_count"] > 0).astype(int)

# Derive label from daily fraud presence
df["label"] = (df["fraud_txn_count"] > 0).astype(int)

missing_features = [c for c in feature_list if c not in df.columns]
if missing_features:
    raise RuntimeError(f"Missing required model features: {missing_features}")

X = df[feature_list].copy()
y = df["label"].astype(int)

print("Rows loaded:", len(df))
print("Fraud rows:", int((y == 1).sum()))
print("Non-fraud rows:", int((y == 0).sum()))

if (y == 1).sum() == 0:
    raise RuntimeError("No fraud-positive rows found in the sampled data. Increase SAMPLE_SIZE.")


# Score
scores = model.predict_proba(X)[:, 1]

plot_df = pd.DataFrame({
    "score": scores,
    "label": y
})

fraud_scores = plot_df.loc[plot_df["label"] == 1, "score"]
nonfraud_scores = plot_df.loc[plot_df["label"] == 0, "score"]

print("Average fraud score:", round(float(fraud_scores.mean()), 4))
print("Average non-fraud score:", round(float(nonfraud_scores.mean()), 4))

# Plot
plt.figure(figsize=(10, 6))

plt.hist(nonfraud_scores, bins=30, alpha=0.65, density=True, label="Non-Fraud")
plt.hist(fraud_scores, bins=30, alpha=0.65, density=True, label="Fraud")

plt.xlabel("Predicted Fraud Probability")
plt.ylabel("Density")
plt.title("Fraud Score Distribution")
plt.legend()
plt.tight_layout()
plt.savefig(output_path, dpi=300, bbox_inches="tight")
plt.show()

print(f"Fraud score distribution chart saved to: {output_path}")
