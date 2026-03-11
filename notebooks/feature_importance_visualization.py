import os
import joblib
import matplotlib.pyplot as plt
import pandas as pd


# Paths
script_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.dirname(script_dir)
docs_dir = os.path.join(repo_root, "docs")
os.makedirs(docs_dir, exist_ok=True)

model_path = os.path.join(
    repo_root,
    "model-training",
    "artifacts",
    "model.joblib"
)

split_output = os.path.join(docs_dir, "feature_importance_split.png")
gain_output = os.path.join(docs_dir, "feature_importance_gain.png")


# Load Model
model = joblib.load(model_path)
booster = model.booster_

feature_names = booster.feature_name()


# SPLIT IMPORTANCE

split_importance = booster.feature_importance(importance_type="split")

df_split = pd.DataFrame({
    "feature": feature_names,
    "importance": split_importance
})

df_split = df_split.sort_values("importance", ascending=False).head(15)

print("\nSplit Importance\n")
print(df_split)


plt.figure(figsize=(10,7))

plt.barh(
    df_split["feature"][::-1],
    df_split["importance"][::-1]
)

plt.xlabel("Number of Splits")
plt.ylabel("Feature")
plt.title("Feature Importance (Split Count)")

plt.tight_layout()

plt.savefig(split_output, dpi=300, bbox_inches="tight")

plt.show()

print(f"Split importance chart saved to: {split_output}")


# GAIN IMPORTANCE
gain_importance = booster.feature_importance(importance_type="gain")

df_gain = pd.DataFrame({
    "feature": feature_names,
    "importance": gain_importance
})

df_gain = df_gain.sort_values("importance", ascending=False).head(15)

print("\nGain Importance\n")
print(df_gain)


plt.figure(figsize=(10,7))

plt.barh(
    df_gain["feature"][::-1],
    df_gain["importance"][::-1]
)

plt.xlabel("Total Gain Contribution")
plt.ylabel("Feature")
plt.title("Feature Importance (Gain)")

plt.tight_layout()

plt.savefig(gain_output, dpi=300, bbox_inches="tight")

plt.show()

print(f"Gain importance chart saved to: {gain_output}")
