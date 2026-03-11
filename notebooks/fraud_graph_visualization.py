import os

import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd

from sqlalchemy import create_engine
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

DB_URI = "postgresql://fraud:fraud@localhost:5432/fraud"
TOP_DEVICES = 10
MAX_ROWS = 1000
FIGSIZE = (14, 10)
DPI = 300
SEED = 42

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.dirname(script_dir)
docs_dir = os.path.join(repo_root, "docs")
os.makedirs(docs_dir, exist_ok=True)
output_path = os.path.join(docs_dir, "fraud_graph_example.png")

engine = create_engine(DB_URI)

# Find the most shared fraud-linked devices
top_devices_query = f"""
WITH fraud_devices AS (
    SELECT
        device_id,
        COUNT(*) AS fraud_txn_count,
        COUNT(DISTINCT user_id) AS user_count,
        COUNT(DISTINCT merchant_id) AS merchant_count
    FROM raw_transactions
    WHERE is_fraud = 1
    GROUP BY device_id
)
SELECT device_id
FROM fraud_devices
WHERE user_count > 1 OR merchant_count > 1
ORDER BY fraud_txn_count DESC, user_count DESC, merchant_count DESC
LIMIT {TOP_DEVICES};
"""

top_devices = pd.read_sql(top_devices_query, engine)["device_id"].tolist()

if not top_devices:
    raise RuntimeError("No shared fraud-linked devices found. Try lowering the filter or checking the data.")

device_list_sql = ", ".join(f"'{d}'" for d in top_devices)

# Pull transactions around those devices
query = f"""
SELECT
    user_id,
    device_id,
    merchant_id,
    is_fraud
FROM raw_transactions
WHERE device_id IN ({device_list_sql})
LIMIT {MAX_ROWS};
"""

df = pd.read_sql(query, engine)

print(f"Top devices selected: {len(top_devices)}")
print(f"Transactions loaded: {len(df)}")

# Build graph
G = nx.Graph()
node_counts = {}

for _, row in df.iterrows():
    user = f"user::{row.user_id}"
    device = f"device::{row.device_id}"
    merchant = f"merchant::{row.merchant_id}"
    is_fraud = int(row.is_fraud)

    for node, node_type in [
        (user, "user"),
        (device, "device"),
        (merchant, "merchant"),
    ]:
        if node not in G:
            G.add_node(node, node_type=node_type, fraud_touched=False)
        node_counts[node] = node_counts.get(node, 0) + 1

    if is_fraud == 1:
        G.nodes[user]["fraud_touched"] = True
        G.nodes[device]["fraud_touched"] = True
        G.nodes[merchant]["fraud_touched"] = True

    for a, b in [(user, device), (device, merchant)]:
        if G.has_edge(a, b):
            G[a][b]["weight"] += 1
            if is_fraud == 1:
                G[a][b]["fraud_edge"] = True
        else:
            G.add_edge(a, b, weight=1, fraud_edge=(is_fraud == 1))

G.remove_nodes_from(list(nx.isolates(G)))

print(f"Rendered nodes: {G.number_of_nodes()}")
print(f"Rendered edges: {G.number_of_edges()}")

# Style
node_colors = []
node_sizes = []

for node, attrs in G.nodes(data=True):
    node_type = attrs["node_type"]
    fraud_touched = attrs.get("fraud_touched", False)

    if node_type == "user":
        color = "deepskyblue" if fraud_touched else "skyblue"
    elif node_type == "device":
        color = "darkorange" if fraud_touched else "orange"
    else:
        color = "green" if fraud_touched else "mediumseagreen"

    node_colors.append(color)
    node_sizes.append(120 + min(node_counts.get(node, 1) * 15, 500))

edge_colors = ["red" if attrs.get("fraud_edge", False) else "lightgray" for _, _, attrs in G.edges(data=True)]
edge_widths = [1.8 if attrs.get("fraud_edge", False) else 0.8 for _, _, attrs in G.edges(data=True)]

# Layout
plt.figure(figsize=FIGSIZE)
pos = nx.spring_layout(G, seed=SEED, k=0.6)

nx.draw_networkx_edges(G, pos, edge_color=edge_colors, width=edge_widths, alpha=0.5)
nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=node_sizes, alpha=0.9)

degrees = dict(G.degree())
top_nodes = sorted(degrees, key=degrees.get, reverse=True)[:15]
labels = {node: node.split("::", 1)[1] for node in top_nodes}

nx.draw_networkx_labels(G, pos, labels=labels, font_size=8)

plt.title(
    "Fraud Network Centered on Shared Devices\n"
    "Users, Devices, and Merchants Linked by Suspicious Transactions",
    fontsize=14
)
plt.axis("off")
plt.tight_layout()
legend_elements = [
    Patch(facecolor='skyblue', label='User'),
    Patch(facecolor='orange', label='Device'),
    Patch(facecolor='mediumseagreen', label='Merchant'),
    Line2D([0], [0], color='red', lw=2, label='Fraud Transaction'),
    Line2D([0], [0], color='lightgray', lw=1, label='Normal Transaction')
]

plt.legend(
    handles=legend_elements,
    loc="upper left",
    frameon=True
)
plt.savefig(output_path, dpi=DPI, bbox_inches="tight")
plt.show()

print(f"Graph saved to: {output_path}")
