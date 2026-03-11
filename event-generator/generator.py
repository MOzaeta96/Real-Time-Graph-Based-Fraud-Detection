import os
import uuid
import json
import time
import random
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from kafka import KafkaProducer


def env_int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def env_float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def env_str(name: str, default: str) -> str:
    return os.getenv(name, default)


def parse_start_date(value: str) -> datetime:
    return datetime.fromisoformat(value)


def generate_transactions(
    n: int,
    users: list[str],
    merchants: list[str],
    devices: list[str],
    start_date: datetime,
    window_days: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    seconds = 60 * 60 * 24 * window_days

    tx_ids = [str(uuid.uuid4()) for _ in range(n)]

    df = pd.DataFrame(
        {
            "transaction_id": tx_ids,
            "timestamp": pd.to_datetime(
                rng.integers(0, seconds, size=n),
                unit="s",
                origin=start_date,
            ),
            "user_id": rng.choice(users, size=n),
            "merchant_id": rng.choice(merchants, size=n),
            "device_id": rng.choice(devices, size=n),
            "amount": np.round(rng.exponential(50, size=n), 2),
            "country": rng.choice(["US", "CA", "UK"], size=n),
            "is_fraud": np.zeros(n, dtype=int),
        }
    )
    return df


def write_outputs(df: pd.DataFrame, output_dir: str, basename: str, fmt: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{basename}.{fmt}")

    if fmt == "parquet":
        df.to_parquet(out_path, index=False)
    elif fmt == "csv":
        df.to_csv(out_path, index=False)
    else:
        raise ValueError("OUTPUT_FORMAT must be 'parquet' or 'csv'")

    marker = os.path.join(output_dir, "_SUCCESS")
    with open(marker, "w", encoding="utf-8") as f:
        f.write(out_path)

    return out_path


def write_metadata(
    output_dir: str,
    out_path: str,
    seed: int,
    num_users: int,
    num_merchants: int,
    num_devices: int,
    num_transactions: int,
    fraud_rate: float,
    start_date: str,
    window_days: int,
    fmt: str,
    fraud_positive_rate_actual: float,
    extra: dict | None = None,
) -> None:
    metadata_path = os.path.join(output_dir, "metadata.json")
    payload = {
        "output_path": out_path,
        "output_format": fmt,
        "seed": seed,
        "num_users": num_users,
        "num_merchants": num_merchants,
        "num_devices": num_devices,
        "num_transactions": num_transactions,
        "fraud_rate_config": fraud_rate,
        "fraud_positive_rate_actual": fraud_positive_rate_actual,
        "start_date": start_date,
        "window_days": window_days,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def publish_to_kafka(
    df: pd.DataFrame,
    bootstrap_servers: str,
    topic: str,
    client_id: str,
    sleep_ms: int = 0,
) -> int:
    producer = KafkaProducer(
        bootstrap_servers=bootstrap_servers,
        client_id=client_id,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda v: v.encode("utf-8"),
        acks="all",
        retries=5,
    )

    sent = 0

    for row in df.itertuples(index=False):
        event = {
            "event_id": str(uuid.uuid4()),
            "event_time": pd.Timestamp(row.timestamp).isoformat(),
            "transaction_id": row.transaction_id,
            "user_id": row.user_id,
            "merchant_id": row.merchant_id,
            "device_id": row.device_id,
            "amount": float(row.amount),
            "country": row.country,
            "is_fraud": int(row.is_fraud),
        }

        producer.send(topic, key=event["transaction_id"], value=event)
        sent += 1

        if sleep_ms > 0:
            time.sleep(sleep_ms / 1000.0)

    producer.flush()
    producer.close()
    return sent


def main() -> None:
    seed = env_int("SEED", 42)

    num_users = env_int("NUM_USERS", 100_000)
    num_merchants = env_int("NUM_MERCHANTS", 10_000)
    num_devices = env_int("NUM_DEVICES", 200_000)
    num_transactions = env_int("NUM_TRANSACTIONS", 1_000_000)

    fraud_rate = env_float("FRAUD_RATE", 0.05)
    TARGET_FRAUD_RATE = fraud_rate

    RISKY_MERCHANT_PCT = env_float("RISKY_MERCHANT_PCT", 0.01)
    COMPROMISED_DEVICE_PCT = env_float("COMPROMISED_DEVICE_PCT", 0.005)
    HIGH_RISK_USER_PCT = env_float("HIGH_RISK_USER_PCT", 0.02)

    MERCHANT_RISK_MULT = env_float("MERCHANT_RISK_MULT", 6.0)
    DEVICE_RISK_MULT = env_float("DEVICE_RISK_MULT", 10.0)
    USER_RISK_MULT = env_float("USER_RISK_MULT", 3.0)

    AMOUNT_SPIKE_MULT = env_float("AMOUNT_SPIKE_MULT", 3.0)
    SPIKE_RATIO = env_float("SPIKE_RATIO", 5.0)
    CONTAGION_MULT = env_float("CONTAGION_MULT", 1.5)
    BASE_FLOOR = env_float("BASE_FLOOR", 0.0005)

    start_date_str = env_str("START_DATE", "2025-01-01")
    window_days = env_int("WINDOW_DAYS", 30)

    output_dir = env_str("OUTPUT_DIR", "/data")
    output_format = env_str("OUTPUT_FORMAT", "parquet")
    output_basename = env_str("OUTPUT_BASENAME", "transactions")

    output_mode = env_str("OUTPUT_MODE", "file").lower()
    kafka_bootstrap_servers = env_str("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    kafka_topic = env_str("KAFKA_TOPIC", "transactions.raw")
    kafka_client_id = env_str("KAFKA_CLIENT_ID", "event-generator")
    kafka_sleep_ms = env_int("KAFKA_SLEEP_MS", 0)

    np.random.seed(seed)
    random.seed(seed)
    rng = np.random.default_rng(seed)

    users = [f"u_{i}" for i in range(num_users)]
    merchants = [f"m_{i}" for i in range(num_merchants)]
    devices = [f"d_{i}" for i in range(num_devices)]

    start_date = parse_start_date(start_date_str)
    df = generate_transactions(
        n=num_transactions,
        users=users,
        merchants=merchants,
        devices=devices,
        start_date=start_date,
        window_days=window_days,
        rng=rng,
    )

    user_id_arr = df["user_id"].to_numpy()
    merchant_id_arr = df["merchant_id"].to_numpy()
    device_id_arr = df["device_id"].to_numpy()
    amount_arr = df["amount"].to_numpy()

    num_risky_merchants = max(1, int(num_merchants * RISKY_MERCHANT_PCT))
    num_compromised_devices = max(1, int(num_devices * COMPROMISED_DEVICE_PCT))
    num_high_risk_users = max(1, int(num_users * HIGH_RISK_USER_PCT))

    risky_merchants = set(rng.choice(merchants, size=num_risky_merchants, replace=False))
    compromised_devices = set(rng.choice(devices, size=num_compromised_devices, replace=False))
    high_risk_users = set(rng.choice(users, size=num_high_risk_users, replace=False))

    m_mult = np.where(np.isin(merchant_id_arr, list(risky_merchants)), MERCHANT_RISK_MULT, 1.0)
    d_mult = np.where(np.isin(device_id_arr, list(compromised_devices)), DEVICE_RISK_MULT, 1.0)
    u_mult = np.where(np.isin(user_id_arr, list(high_risk_users)), USER_RISK_MULT, 1.0)

    user_baseline = df.groupby("user_id")["amount"].median()
    baseline_arr = df["user_id"].map(user_baseline).to_numpy()
    spike = amount_arr > (SPIKE_RATIO * baseline_arr)
    a_mult = np.where(spike, AMOUNT_SPIKE_MULT, 1.0)

    propensity = m_mult * d_mult * u_mult * a_mult

    p = 0.01 * propensity
    mean_p = float(np.mean(p))
    scale = TARGET_FRAUD_RATE / mean_p if mean_p > 0 else 1.0
    p = np.clip(p * scale, 0.0, 0.99)

    is_fraud_0 = (rng.random(size=len(p)) < p).astype(int)

    tmp = df[["user_id", "timestamp"]].copy()
    tmp["date"] = pd.to_datetime(tmp["timestamp"]).dt.date
    tmp["is_fraud_0"] = is_fraud_0

    user_day_fraud = tmp.groupby(["user_id", "date"])["is_fraud_0"].max().reset_index()
    user_day_fraud["date_next"] = (pd.to_datetime(user_day_fraud["date"]) + pd.Timedelta(days=1)).dt.date

    contagion_keys = set(
        zip(
            user_day_fraud.loc[user_day_fraud["is_fraud_0"] == 1, "user_id"],
            user_day_fraud.loc[user_day_fraud["is_fraud_0"] == 1, "date_next"],
        )
    )

    df_dates = pd.to_datetime(df["timestamp"]).dt.date.to_numpy()
    contagion_mask = np.array(
        [(u, d) in contagion_keys for u, d in zip(df["user_id"].to_numpy(), df_dates)],
        dtype=bool,
    )
    p2 = p * np.where(contagion_mask, CONTAGION_MULT, 1.0)
    p2 = np.clip(p2 + BASE_FLOOR, 0.0, 0.99)

    mean_p2 = float(np.mean(p2))
    scale2 = TARGET_FRAUD_RATE / mean_p2 if mean_p2 > 0 else 1.0
    p2 = np.clip(p2 * scale2, 0.0, 0.99)

    df["is_fraud"] = (rng.random(size=len(p2)) < p2).astype(int)
    fraud_positive_rate_actual = float(df["is_fraud"].mean())

    extra = {
        "fraud_mechanisms": {
            "target_fraud_rate": TARGET_FRAUD_RATE,
            "risky_merchant_pct": RISKY_MERCHANT_PCT,
            "compromised_device_pct": COMPROMISED_DEVICE_PCT,
            "high_risk_user_pct": HIGH_RISK_USER_PCT,
            "merchant_risk_mult": MERCHANT_RISK_MULT,
            "device_risk_mult": DEVICE_RISK_MULT,
            "user_risk_mult": USER_RISK_MULT,
            "amount_spike_mult": AMOUNT_SPIKE_MULT,
            "spike_ratio": SPIKE_RATIO,
            "contagion_mult": CONTAGION_MULT,
            "output_mode": output_mode,
        }
    }

    if output_mode == "kafka":
        sent = publish_to_kafka(
            df=df,
            bootstrap_servers=kafka_bootstrap_servers,
            topic=kafka_topic,
            client_id=kafka_client_id,
            sleep_ms=kafka_sleep_ms,
        )

        write_metadata(
            output_dir=output_dir,
            out_path=f"kafka://{kafka_bootstrap_servers}/{kafka_topic}",
            seed=seed,
            num_users=num_users,
            num_merchants=num_merchants,
            num_devices=num_devices,
            num_transactions=num_transactions,
            fraud_rate=fraud_rate,
            start_date=start_date_str,
            window_days=window_days,
            fmt="kafka",
            fraud_positive_rate_actual=fraud_positive_rate_actual,
            extra=extra,
        )

        print(
            f"[event-generator] published={sent:,} fraud_positive_rate={fraud_positive_rate_actual:.4f} topic={kafka_topic}"
        )
    else:
        out_path = write_outputs(df, output_dir, output_basename, output_format)

        write_metadata(
            output_dir=output_dir,
            out_path=out_path,
            seed=seed,
            num_users=num_users,
            num_merchants=num_merchants,
            num_devices=num_devices,
            num_transactions=num_transactions,
            fraud_rate=fraud_rate,
            start_date=start_date_str,
            window_days=window_days,
            fmt=output_format,
            fraud_positive_rate_actual=fraud_positive_rate_actual,
            extra=extra,
        )

        print(
            f"[event-generator] rows={len(df):,} fraud_positive_rate={fraud_positive_rate_actual:.4f} -> {out_path}"
        )


if __name__ == "__main__":
    main()
