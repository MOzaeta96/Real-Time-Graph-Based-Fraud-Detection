**Generating Data:**

The first step was to create the starting point data for the generator.

The desire is to create something that reflects real-world dynamics, supports streaming feature engineering, and scales well while still preserving temporal correctness and meaningful model decisions.

**Reproducibility**

Random seeds were fixed during synthetic data generation.

This guarantees that:

Fraud patterns remain consistent across runs

Feature distributions remain stable

Model evaluation metrics are comparable

Debugging and regression testing are possible

Deterministic data generation is critical in machine learning pipelines to avoid non-reproducible results.
"""

import numpy as np
import pandas as pd
import uuid
import random
from datetime import datetime, timedelta

np.random.seed(42)
random.seed(42)

"""The large about of transactions were chosen because real sales are right-skewed, i.e, most purchases are small in quantity, frequent, and of lower value.

The fraud rate was set to 5% as a 2023 TransUnion Study shows that 5% of all global digital transactions were suspected to be digital fraud, with ACH/Debit and Credit Cards going higher than 6%.

We want to keep track of the event time and separate it from processing time in order to more realistically represent streaming systems and feature consistency since network delays and out of order events occur in real systems.

We'll want to use the user_id as the primary partition key to replicate the fact that most faud signals are at the user level (i.e. device reuse, spending anomalies), and to allow for more efficient aggregation.
"""

NUM_USERS = 100_000
NUM_MERCHANTS = 10_000
NUM_DEVICES = 200_000
NUM_TRANSACTIONS = 1_000_000

FRAUD_RATE = 0.05
START_DATE = datetime(2025, 1, 1)

"""The data set size was chosen to simulate as large of a production-scale batch as possible, while still allowing the system to run from a local s docker set up."""

users = [f"u_{i}" for i in range(NUM_USERS)]
merchants = [f"m_{i}" for i in range(NUM_MERCHANTS)]
devices = [f"d_{i}" for i in range(NUM_DEVICES)]

"""**Event Schema**

| Field          | Type     | Description              |
| -------------- | -------- | ------------------------ |
| transaction_id | UUID     | Unique event identifier  |
| timestamp      | datetime | Event time               |
| user_id        | string   | Unique user identifier   |
| merchant_id    | string   | Merchant identifier      |
| device_id      | string   | Device fingerprint       |
| amount         | float    | Transaction amount (USD) |
| country        | string   | Transaction country      |
| is_fraud       | int      | Binary fraud label       |

"""

def random_timestamp():
    return START_DATE + timedelta(
        seconds=random.randint(0, 60*60*24*30)
    )

def generate_transactions(n):
    df = pd.DataFrame({
        "transaction_id": [str(uuid.uuid4()) for _ in range(n)],
        "timestamp": pd.to_datetime(
            np.random.randint(0, 60*60*24*30, n),
            unit="s",
            origin=START_DATE
        ),
        "user_id": np.random.choice(users, n),
        "merchant_id": np.random.choice(merchants, n),
        "device_id": np.random.choice(devices, n),
        "amount": np.round(np.random.exponential(50, n), 2),
        "country": np.random.choice(["US", "CA", "UK"], n),
        "is_fraud": 0
    })

    return df


df = generate_transactions(NUM_TRANSACTIONS)

"""Vectorized NumPy operations were used to ensure the generator scales to tens of millions of transactions. A more simple row-wise loop would be memory inefficient and add far too much processing time for a large-scale data set."""

fraud_users = random.sample(users, int(NUM_USERS * FRAUD_RATE))

df.loc[df["user_id"].isin(fraud_users), "is_fraud"] = 1

"""**Fraud Simulation Limitations**

The current fraud labeling assigns fraud at the user level for initial system prototyping and will serve as a baseline to get the project up and running.

This simplifies class imbalance modeling, early feature engineering, and infrastructure validation

However, it does not yet simulate things like transaction velocity bursts, device-sharing fraud rings, geographic impossibility, or merchant collusion.

These might be introduced in subsequent iterations to enhance graph-based feature modeling, but the current goal is to get a realistic simulation running for analysis purposes.
"""
