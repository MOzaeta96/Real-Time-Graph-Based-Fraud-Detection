import json
import random
import time
import urllib.request

API_URL = "http://localhost:8000/score"
N = 500
USER_MAX = 100000

latencies = []
errors = 0

latencies = []
errors = 0

t_all = time.time()   # ← START TOTAL TIMER

for i in range(N):
    user_id = f"u_{random.randint(0, USER_MAX-1)}"
    payload = {
        "user_id": user_id,
        "amount": round(random.random() * 500, 2),
        "country": "US",
    }

    t0 = time.time()
    try:
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            _ = resp.read()
        lat = (time.time() - t0) * 1000
        latencies.append(lat)
    except Exception:
        errors += 1

    if (i + 1) % 50 == 0:
        print(f"{i+1}/{N} done...")

total_s = time.time() - t_all   # ← END TOTAL TIMER

latencies.sort()
def pct(p):
    if not latencies:
        return None
    k = int(len(latencies) * p)
    k = min(max(k, 0), len(latencies) - 1)
    return latencies[k]

print("\nRESULTS")
print(f"requests: {N}")
print(f"success:  {len(latencies)}")
print(f"errors:   {errors}")
if latencies:
    print(f"p50 ms:   {pct(0.50):.2f}")
    print(f"p90 ms:   {pct(0.90):.2f}")
    print(f"p99 ms:   {pct(0.99):.2f}")
    print(f"max ms:   {max(latencies):.2f}")
print(f"total_time_s: {total_s:.2f}")
if total_s > 0:
    print(f"rps: {len(latencies)/total_s:.2f}")
