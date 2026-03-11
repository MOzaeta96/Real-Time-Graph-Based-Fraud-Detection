import os
import redis
import json
import time
from prometheus_client import start_http_server, Gauge

REDIS_HOST = os.getenv("REDIS_HOST", "redis")

STREAM = "fraud_predictions"

r = redis.Redis(host=REDIS_HOST, decode_responses=True)

AVG_SCORE = Gauge(
    "fraud_prediction_avg_score",
    "Average fraud score over last window"
)

FRAUD_RATE = Gauge(
    "fraud_prediction_rate",
    "Fraction of predictions above threshold"
)

WINDOW = 5000


def main():

    start_http_server(9103)

    scores = []

    last_id = "0-0"

    while True:

        data = r.xread({STREAM: last_id}, block=5000, count=100)

        if not data:
            continue

        for stream, messages in data:
            for msg_id, fields in messages:

                last_id = msg_id

                score = float(fields["score"])
                scores.append(score)

                if len(scores) > WINDOW:
                    scores.pop(0)

        if scores:
            avg = sum(scores)/len(scores)
            fraud_rate = sum(s>0.5 for s in scores)/len(scores)

            AVG_SCORE.set(avg)
            FRAUD_RATE.set(fraud_rate)


if __name__ == "__main__":
    main()
